"""Demo set for the upload workflow: before/after image pairs from the xBD hold split in the forms a user brings,
with a metadata.json per scenario that the upload dialog can read (name, type, date, corner coordinates).

  <out>/<NN_event>/pre.tif  post.tif   GeoTIFF pair: the georeferencing is inside the files
  <out>/<NN_event>/pre.jpg  post.jpg   plain JPEG pair: corner coordinates are in metadata.json
  <out>/<NN_event>/metadata.json       name, disaster type, event date, corners of each image, presenter notes
  <out>/README.md, scenarios.csv       what each scenario is and what xBD says is on the ground (not given to the app)

The hold split was never used for training or model selection. Truth counts come from the xBD labels and are only
for the presenter to compare with; the app never sees them.

  uv run --no-sync python app/scripts/make_demo_set.py [out_dir]
"""
import json
import sys
from pathlib import Path

import cv2
import pandas as pd
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.api.engines import ROOT, XBD  # noqa: E402
from app.api.imagery import write_geotiff  # noqa: E402
from app.api.scenes import catalogue, geotransforms, pixel_size_m  # noqa: E402

EVENTS = [  # (event, why this one)
    ("santa-rosa-wildfire", "whole neighbourhood burnt: clear high-severity alerts"),
    ("hurricane-michael", "wind damage to roofs and tree fall: a mix of classes"),
    ("palu-tsunami", "tsunami and earthquake: destroyed and intact blocks side by side"),
    ("hurricane-harvey", "flooding: damage that is hard to see from above (known weak spot)"),
    ("mexico-earthquake", "earthquake: few collapsed buildings in a dense city"),
    ("socal-fire", "fire: scattered losses"),
    ("midwest-flooding", "river flooding: mostly intact roofs"),
    ("guatemala-volcano", "little visible damage: should raise no or few alerts"),
]
TYPE = {"wildfire": "fire", "fire": "fire", "wind": "wind", "tsunami": "tsunami", "flooding": "flooding",
        "earthquake": "earthquake", "volcano": "volcano"}


def corners(gt, n=1024):
    return {"west": gt[0], "south": gt[3] + n * gt[5], "east": gt[0] + n * gt[1], "north": gt[3]}


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    cat = catalogue()
    cat = cat[cat.split == "hold"]
    imgs = pd.read_parquet(ROOT / "data/xbd/_meta/images.parquet", columns=["event_id", "phase", "capture_date"])
    dates = imgs.pivot_table(index="event_id", columns="phase", values="capture_date", aggfunc="first")
    gts = geotransforms()
    rows, readme = [], []
    for i, (ev, why) in enumerate(EVENTS, 1):
        sub = cat[cat.disaster == ev]
        if sub.empty:
            continue
        r = sub.sort_values("severe_true").iloc[-1] if i != len(EVENTS) else sub.sort_values("severe_true").iloc[0]
        pid = r.pair_id
        d = out / f"{i:02d}_{ev}"
        d.mkdir(exist_ok=True)
        meta = {"name": f"{ev.replace('-', ' ').title()} ({pid.split('_')[-1]})",
                "disaster_type": TYPE.get(r.disaster_type, "other"),
                "event_date": str(dates.loc[pid, "post"])[:10],
                "before_date": str(dates.loc[pid, "pre"])[:10], "source_tile": pid, "why": why}
        for ph in ("pre", "post"):
            rgb = cv2.cvtColor(cv2.imread(str(XBD / r.split / "images" / f"{pid}_{ph}_disaster.png")), cv2.COLOR_BGR2RGB)
            gt = gts[f"{pid}_{ph}_disaster.png"][0]
            write_geotiff(d / f"{ph}.tif", rgb, Affine.from_gdal(*gt))
            cv2.imwrite(str(d / f"{ph}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
            meta["before_corners" if ph == "pre" else "after_corners"] = corners(gt)
        (d / "metadata.json").write_text(json.dumps(meta, indent=2))
        t = {"destroyed": int(r.true_destroyed), "major": int(r.true_major), "minor": int(r.true_minor), "none": int(r.true_none)}
        rows.append({"folder": d.name, "name": meta["name"], "type": meta["disaster_type"], "event_date": meta["event_date"],
                     "centre_lat": round(r.centre_lat, 5), "centre_lon": round(r.centre_lon, 5), "pixel_size_m": round(pixel_size_m(pid), 2),
                     **{f"xbd_{k}": v for k, v in t.items()}, "why": why})
        print(d.name, meta["name"], t)
    df = pd.DataFrame(rows)
    df.to_csv(out / "scenarios.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs" / "app" / "demo_set")
