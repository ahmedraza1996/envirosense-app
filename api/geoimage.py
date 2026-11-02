"""North-up copies of an image for the street-map view.

A Leaflet image overlay is an axis-aligned rectangle in longitude/latitude. A georeferenced image whose pixel grid is
rotated against north (typical for UTM GeoTIFFs: the grid convergence is up to a few degrees) would land shifted by tens
of metres at its corners while its outlines, which follow the full geotransform, stay put. For such images the overlay
is resampled onto a north-up longitude/latitude grid using the same geotransform as the outlines, so image and outlines
agree exactly.
"""
import numpy as np
import cv2

ROTATION_LIMIT = 1e-4      # off-diagonal / diagonal terms of the geotransform; 1e-4 over 2 km is 0.2 m
MAX_SIDE = 5000


def is_rotated(gt) -> bool:
    return abs(gt[2]) > ROTATION_LIMIT * abs(gt[1]) or abs(gt[4]) > ROTATION_LIMIT * abs(gt[5])


def grid(gt, w, h, px_m):
    """North-up grid covering the image: (west, north, dlon, dlat, width, height); about px_m per cell."""
    cs = [(gt[0] + x * gt[1] + y * gt[2], gt[3] + x * gt[4] + y * gt[5]) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
    west, east = min(c[0] for c in cs), max(c[0] for c in cs)
    south, north = min(c[1] for c in cs), max(c[1] for c in cs)
    dlat = px_m / 110_574
    dlon = px_m / (111_320 * np.cos(np.radians((south + north) / 2)))
    nw, nh = int(np.ceil((east - west) / dlon)), int(np.ceil((north - south) / dlat))
    s = min(1.0, MAX_SIDE / max(nw, nh))
    return west, north, dlon / s, dlat / s, int(np.ceil(nw * s)), int(np.ceil(nh * s))


def bounds(gt, w, h, px_m):
    """[[south, west], [north, east]] as Leaflet wants them."""
    west, north, dlon, dlat, nw, nh = grid(gt, w, h, px_m)
    return [[north - nh * dlat, west], [north, west + nw * dlon]]


def north_up(img: np.ndarray, gt, px_m: float) -> bytes:
    """img: H x W x 3 or 4 uint8. Returns a WebP with alpha: transparent outside the image."""
    h, w = img.shape[:2]
    west, north, dlon, dlat, nw, nh = grid(gt, w, h, px_m)
    A = np.array([[gt[1], gt[2]], [gt[4], gt[5]]])
    Ainv = np.linalg.inv(A)
    # output pixel index (u, v) -> pixel centre -> lon/lat -> source pixel edge coordinates -> source pixel index
    lonlat = np.array([[dlon, 0, west + dlon / 2], [0, -dlat, north - dlat / 2], [0, 0, 1]])
    src = np.eye(3)
    src[:2, :2], src[:2, 2] = Ainv, -Ainv @ np.array([gt[0], gt[3]]) - 0.5
    M = (src @ lonlat)[:2]
    # an RGB image has no alpha: pure black is nodata (the empty corners of a reprojected image), so it stays transparent
    rgba = img if img.shape[2] == 4 else np.dstack([img, np.where(img.max(-1) > 0, 255, 0).astype(np.uint8)])
    out = cv2.warpAffine(np.ascontiguousarray(rgba), M, (nw, nh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    ok, buf = cv2.imencode(".webp", cv2.cvtColor(out, cv2.COLOR_RGBA2BGRA), [cv2.IMWRITE_WEBP_QUALITY, 88])
    if not ok:
        raise RuntimeError("could not encode the north-up image")
    return buf.tobytes()
