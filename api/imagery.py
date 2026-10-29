"""Georeferenced imagery for uploads: read, reproject onto a common grid, align before/after.

Accepted inputs: GeoTIFF (CRS + transform inside the file) or a plain PNG/JPEG with north-up corner coordinates.
All processing happens on the after image's own pixel grid.
"""
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import Affine, from_bounds
from rasterio.warp import Resampling, reproject

WGS84 = CRS.from_epsg(4326)


class ImageryError(ValueError):
    pass


@dataclass
class GeoImage:
    rgb: np.ndarray          # H x W x 3 uint8
    crs: CRS
    transform: Affine        # pixel (col, row) -> CRS coordinates

    @property
    def shape(self):
        return self.rgb.shape[:2]


def _to_uint8(bands: np.ndarray) -> np.ndarray:
    if bands.dtype == np.uint8:
        return bands
    out = np.zeros(bands.shape, np.uint8)
    for i, b in enumerate(bands.astype(np.float32)):   # per-band 2-98% stretch for 16-bit / float imagery
        lo, hi = np.percentile(b[b > 0] if (b > 0).any() else b, [2, 98])
        out[i] = np.clip((b - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    return out


def read_image(path: Path, bounds: dict | None = None) -> GeoImage:
    """bounds = {"west", "south", "east", "north"} in degrees, required when the file carries no georeferencing."""
    path = Path(path)
    if path.suffix.lower() in (".tif", ".tiff"):
        with rasterio.open(path) as src:
            if src.count < 3:
                raise ImageryError(f"{path.name}: needs 3 bands (RGB), found {src.count}")
            rgb = _to_uint8(src.read([1, 2, 3])).transpose(1, 2, 0)
            crs, tf = src.crs, src.transform
        if crs is None or tf == Affine.identity():
            if not bounds:
                raise ImageryError(f"{path.name}: GeoTIFF has no georeferencing; give its corner coordinates")
            crs, tf = WGS84, from_bounds(bounds["west"], bounds["south"], bounds["east"], bounds["north"], rgb.shape[1], rgb.shape[0])
    else:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ImageryError(f"{path.name}: not a readable image")
        if not bounds:
            raise ImageryError(f"{path.name}: plain images need corner coordinates (west, south, east, north)")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        crs, tf = WGS84, from_bounds(bounds["west"], bounds["south"], bounds["east"], bounds["north"], rgb.shape[1], rgb.shape[0])
    return GeoImage(np.ascontiguousarray(rgb), crs, tf)


def to_lonlat_fn(g: GeoImage):
    tr = None if g.crs == WGS84 else Transformer.from_crs(g.crs, WGS84, always_xy=True)

    def f(x, y):
        X, Y = g.transform @ (x, y)
        return (X, Y) if tr is None else tr.transform(X, Y)
    return f


def footprint_lonlat(g: GeoImage):
    from shapely.geometry import Polygon
    f = to_lonlat_fn(g)
    h, w = g.shape
    return Polygon([f(0, 0), f(w, 0), f(w, h), f(0, h)])


def pixel_size_m(g: GeoImage) -> float:
    f = to_lonlat_fn(g)
    h, w = g.shape
    (lon0, lat0), (lon1, lat1) = f(0, h / 2), f(w, h / 2)
    dx = (lon1 - lon0) * 111_320 * math.cos(math.radians((lat0 + lat1) / 2))
    return math.hypot(dx, (lat1 - lat0) * 110_574) / w


def approx_geotransform(g: GeoImage) -> list:
    """GDAL-order affine from pixels to lon/lat (exact for EPSG:4326 inputs, a close fit for small projected images);
    the app's map view uses it to place the image."""
    f = to_lonlat_fn(g)
    h, w = g.shape
    (x0, y0), (xw, yw), (xh, yh) = f(0, 0), f(w, 0), f(0, h)
    return [x0, (xw - x0) / w, (xh - x0) / h, y0, (yw - y0) / w, (yh - y0) / h]


def reproject_into(rgb: np.ndarray, transform: Affine, crs: CRS, dst: GeoImage):
    """Resample an image onto dst's grid. Returns (rgb, valid mask)."""
    h, w = dst.shape
    out = np.zeros((3, h, w), np.uint8)
    for i in range(3):
        reproject(np.ascontiguousarray(rgb[..., i]), out[i], src_transform=transform, src_crs=crs,
                  dst_transform=dst.transform, dst_crs=dst.crs, resampling=Resampling.bilinear, src_nodata=None, dst_nodata=0)
    ones = np.ones(rgb.shape[:2], np.uint8)
    valid = np.zeros((h, w), np.uint8)
    reproject(ones, valid, src_transform=transform, src_crs=crs, dst_transform=dst.transform, dst_crs=dst.crs,
              resampling=Resampling.nearest, dst_nodata=0)
    return out.transpose(1, 2, 0), valid.astype(bool)


def estimate_shift(pre: np.ndarray, post: np.ndarray, valid: np.ndarray):
    """Translation of pre relative to post (pixels) by phase correlation over the valid area, and its peak response.
    Images are smoothed and halved first: phase correlation weights all frequencies equally, so fine detail and JPEG
    noise can bury the true peak (on xBD tiles this version agrees between PNG and JPEG copies and recovers injected
    offsets; the raw version did not). Disasters change the scene, so responses stay modest even when it is right."""
    ys, xs = np.nonzero(valid)
    if len(ys) < 0.25 * valid.size:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1

    def prep(img):
        g = cv2.GaussianBlur(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 2)
        return cv2.resize(g, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    a, b = prep(post), prep(pre)
    win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    return 2 * float(dx), 2 * float(dy), float(resp)


def shift_image(img: np.ndarray, valid: np.ndarray, dx: float, dy: float):
    """Move pre by (-dx, -dy) so it lines up with post."""
    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
    h, w = valid.shape
    return (cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=0),
            cv2.warpAffine(valid.astype(np.uint8), m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0).astype(bool))


def write_geotiff(path: Path, rgb: np.ndarray, transform: Affine, crs: CRS = WGS84):
    with rasterio.open(path, "w", driver="GTiff", width=rgb.shape[1], height=rgb.shape[0], count=3, dtype="uint8",
                       crs=crs, transform=transform, compress="deflate") as dst:
        dst.write(rgb.transpose(2, 0, 1))
