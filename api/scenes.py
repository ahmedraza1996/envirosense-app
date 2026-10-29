"""Scene catalogue: one row per xBD pre/post pair that contains buildings, with true class counts and location."""
import json
import math
from functools import lru_cache
from pathlib import Path

import cv2
import pandas as pd

from .engines import ROOT, XBD

CACHE = ROOT / "runs" / "app" / "cache"


@lru_cache(maxsize=1)
def geotransforms() -> dict:
    return json.loads((XBD / "geotransforms" / "xview_geotransforms.json").read_text())


def pixel_size_m(pair_id: str) -> float:
    t = geotransforms()[f"{pair_id}_post_disaster.png"][0]
    return abs(t[1]) * 111_320 * math.cos(math.radians(t[3]))


def centre_lat_lon(pair_id: str):
    t = geotransforms()[f"{pair_id}_post_disaster.png"][0]
    return t[3] + 512 * t[5], t[0] + 512 * t[1]


@lru_cache(maxsize=1)
def catalogue() -> pd.DataFrame:
    idx = pd.read_parquet(ROOT / "data/xbd_crops/index.parquet",
                          columns=["pair_id", "official_split", "disaster", "disaster_type", "label"])
    g = idx.groupby("pair_id")
    df = pd.DataFrame({"split": g.official_split.first(), "disaster": g.disaster.first(),
                       "disaster_type": g.disaster_type.first(), "buildings": g.size()})
    counts = idx.pivot_table(index="pair_id", columns="label", aggfunc="size", fill_value=0)
    for lab, name in [(0, "true_none"), (1, "true_minor"), (2, "true_major"), (3, "true_destroyed"), (-1, "true_unclassified")]:
        df[name] = counts[lab] if lab in counts else 0
    imgs = pd.read_parquet(ROOT / "data/xbd/_meta/images.parquet", columns=["event_id", "phase", "capture_date"])
    dates = imgs.pivot_table(index="event_id", columns="phase", values="capture_date", aggfunc="first")
    df["pre_date"] = dates["pre"].reindex(df.index).str[:10]
    df["post_date"] = dates["post"].reindex(df.index).str[:10]
    df["severe_true"] = df.true_major + df.true_destroyed
    return df.reset_index().rename(columns={"index": "pair_id"})


def scene(pair_id: str) -> dict:
    df = catalogue()
    row = df[df.pair_id == pair_id]
    if row.empty:
        raise KeyError(pair_id)
    r = {k: (v.item() if hasattr(v, "item") else v) for k, v in row.iloc[0].to_dict().items()}  # numpy -> python
    lat, lon = centre_lat_lon(pair_id)
    return {**r, "centre_lat": lat, "centre_lon": lon, "pixel_size_m": pixel_size_m(pair_id), "size_px": 1024}


def image_jpeg(pair_id: str, phase: str) -> Path:
    """Full 1024 image as JPEG (much smaller than the PNG for the browser), cached on disk."""
    out = CACHE / "images" / f"{pair_id}_{phase}.jpg"
    if not out.exists():
        split = scene(pair_id)["split"]
        out.parent.mkdir(parents=True, exist_ok=True)
        img = cv2.imread(str(XBD / split / "images" / f"{pair_id}_{phase}_disaster.png"))
        cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out
