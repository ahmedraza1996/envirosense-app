"""Sample uploads for trying the upload workflow: after images from xBD hold tiles, written the way a user would
bring them (no labels, no before image).

  runs/app/samples/<tile>_after.tif        GeoTIFF, georeferencing inside the file
  runs/app/samples/<tile>_after.jpg        plain JPEG; its corner coordinates are in samples.json
  runs/app/samples/<tile>_after_offset.tif GeoTIFF whose georeferencing is 8 px (about 4 m) off, to exercise alignment

  uv run --no-sync python app/scripts/make_sample_uploads.py
"""
import json
import sys
from pathlib import Path

import cv2
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.api.engines import XBD, ROOT  # noqa: E402
from app.api.imagery import write_geotiff  # noqa: E402
from app.api.scenes import catalogue, geotransforms  # noqa: E402

OUT = ROOT / "runs" / "app" / "samples"
OFFSET_PX = 8


def pick() -> list:
    """The most damaged hold tile of three different events."""
    df = catalogue()
    df = df[df.split == "hold"]
    return [df[df.disaster == d].sort_values("severe_true").iloc[-1] for d in
            ("santa-rosa-wildfire", "palu-tsunami", "hurricane-michael") if (df.disaster == d).any()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    listing = []
    for r in pick():
        pid = r.pair_id
        rgb = cv2.cvtColor(cv2.imread(str(XBD / r.split / "images" / f"{pid}_post_disaster.png")), cv2.COLOR_BGR2RGB)
        gt = geotransforms()[f"{pid}_post_disaster.png"][0]
        tf = Affine.from_gdal(*gt)
        write_geotiff(OUT / f"{pid}_after.tif", rgb, tf)
        write_geotiff(OUT / f"{pid}_after_offset.tif", rgb, tf * Affine.translation(OFFSET_PX, 0))
        cv2.imwrite(str(OUT / f"{pid}_after.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
        west, north = gt[0], gt[3]
        east, south = gt[0] + 1024 * gt[1], gt[3] + 1024 * gt[5]
        listing.append({"tile": pid, "disaster": r.disaster, "disaster_type": r.disaster_type, "post_date": r.post_date,
                        "jpeg_corners": {"west": west, "south": south, "east": east, "north": north}})
        print(pid, f"W {west:.6f} S {south:.6f} E {east:.6f} N {north:.6f}")
    (OUT / "samples.json").write_text(json.dumps(listing, indent=1))


if __name__ == "__main__":
    main()
