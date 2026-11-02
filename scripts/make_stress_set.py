"""Two extra demo scenarios that show what the upload pipeline corrects, built from scenario 04 (Hurricane Harvey) of the
demo set. A flooded neighbourhood keeps its roads, parcels and roofs, so before and after share many image features; in a
completely burnt area (scenario 01) there is almost nothing left to match and registration reports that instead:

  09_misregistered-before   the before image is rotated 3 degrees, zoomed 3% and shifted 22 px (11 m) against the after image,
                            as a different pass or sensor would give. The app registers it from matching image features.
  11_large-area             one tile repeated 3 x 2 (about 1.4 x 0.9 km): the app processes it block by block with progress. The ground is
                            repeated, so alerts repeat; it tests the pipeline, not the model.
  10_utm-rotated-grid       both images in UTM zone 13 although the scene lies in zone 15: the pixel grid is turned about 4.7 degrees
                            against north. The app has to place image and outlines on the street map together.

  uv run --no-sync python app/scripts/make_stress_set.py [demo_dir]
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import Resampling, calculate_default_transform, reproject

ROOT = Path(__file__).resolve().parents[2]
BASE = "04_hurricane-harvey"


def read(path):
    with rasterio.open(path) as src:
        return src.read(), src.profile, src.transform, src.crs


def misregistered(d: Path, out: Path):
    pre, prof, tf, crs = read(d / "pre.tif")
    img = pre.transpose(1, 2, 0)
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 3.0, 1.03)
    m[:, 2] += (22, -10)
    warped = cv2.warpAffine(np.ascontiguousarray(img), m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out.mkdir(exist_ok=True)
    with rasterio.open(out / "pre.tif", "w", **prof) as dst:
        dst.write(warped.transpose(2, 0, 1))
    (out / "post.tif").write_bytes((d / "post.tif").read_bytes())
    return {"what": "before image rotated 3 degrees, zoomed 3% and shifted 22 px (11 m) against the after image",
            "expect": "Before image panel: registered by DISK + LightGlue from about 115 matching features: rotation +3.3 degrees, zoom -2.8%, offset about 11 m, corrected"}


def utm(d: Path, out: Path, epsg=32613):
    out.mkdir(exist_ok=True)
    dst_crs = CRS.from_epsg(epsg)
    for name in ("pre", "post"):
        with rasterio.open(d / f"{name}.tif") as src:
            tf, w, h = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=0.46)
            prof = {**src.profile, "crs": dst_crs, "transform": tf, "width": w, "height": h, "nodata": 0}
            with rasterio.open(out / f"{name}.tif", "w", **prof) as dst:
                for b in range(1, src.count + 1):
                    reproject(rasterio.band(src, b), rasterio.band(dst, b), src_transform=src.transform, src_crs=src.crs,
                              dst_transform=tf, dst_crs=dst_crs, resampling=Resampling.bilinear)
    return {"what": f"both images in UTM zone 13 (EPSG:{epsg}) although the scene is in zone 15: the pixel grid is turned about 4.7 degrees against north",
            "expect": "Map view: outlines and the satellite image stay together, and the image sits on the right streets"}


def large(d: Path, out: Path, nx=3, ny=2):
    out.mkdir(exist_ok=True)
    for name in ("pre", "post"):
        arr, prof, tf, crs = read(d / f"{name}.tif")
        big = np.tile(arr, (1, ny, nx))
        prof = {**prof, "width": big.shape[2], "height": big.shape[1]}
        with rasterio.open(out / f"{name}.tif", "w", **prof) as dst:
            dst.write(big)
    return {"what": f"the same tile repeated {nx} x {ny}: {nx * 1024} x {ny * 1024} px, processed in blocks of 1024 px",
            "expect": "Status line counts the blocks while it runs (a few minutes on CPU); alerts repeat once per copy; the Before image panel shows the registration of the whole mosaic"}


def main(demo: Path):
    base = demo / BASE
    meta = json.loads((base / "metadata.json").read_text())
    for folder, fn in (("09_misregistered-before", misregistered), ("10_utm-rotated-grid", utm), ("11_large-area", large)):
        out = demo / folder
        note = fn(base, out)
        label = {"09": "misregistered before image", "10": "UTM zone 13 grid", "11": "3 x 2 tiles"}[folder[:2]]
        (out / "metadata.json").write_text(json.dumps({
            "name": f"{meta['name'].split(' (')[0]} ({label})", "disaster_type": meta["disaster_type"], "event_date": meta["event_date"],
            "before_date": meta.get("before_date"), "source_tile": meta["source_tile"], **note}, indent=2))
        print("wrote", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs" / "app" / "demo_set")
