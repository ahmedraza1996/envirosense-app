"""Before-image archives. An archive answers: which earlier images cover this footprint, taken before this date?

XBDArchive: the before images of all 11,034 xBD tiles (train, tier3, test, hold) with their georeferencing, standing
in for a commercial archive. Another provider (e.g. Maxar Open Data) only needs the same search/load interface.
Only before images are used from the archive; no labels.
"""
from functools import lru_cache

import cv2
import pandas as pd
from rasterio.transform import Affine
from shapely import STRtree
from shapely.geometry import Polygon

from .engines import ROOT, XBD
from .imagery import WGS84
from .scenes import geotransforms


class XBDArchive:
    name = "xbd-archive"

    def __init__(self):
        imgs = pd.read_parquet(ROOT / "data/xbd/_meta/images.parquet", columns=["split", "name", "event_id", "phase", "capture_date"])
        pre = imgs[imgs.phase == "pre"].reset_index(drop=True)
        gts = geotransforms()
        rows, polys = [], []
        for r in pre.itertuples():
            g = gts.get(f"{r.name}.png")
            if not g:
                continue
            t = g[0]
            corner = lambda x, y: (t[0] + x * t[1] + y * t[2], t[3] + x * t[4] + y * t[5])
            polys.append(Polygon([corner(0, 0), corner(1024, 0), corner(1024, 1024), corner(0, 1024)]))
            rows.append({"tile": r.event_id, "split": r.split, "name": r.name, "capture_date": (r.capture_date or "")[:10], "gt": t})
        self.rows, self.polys, self.tree = rows, polys, STRtree(polys)

    def search(self, footprint: Polygon, before: str | None = None, limit: int = 4) -> list:
        """Tiles overlapping the footprint, largest overlap first; with `before`, only images captured earlier."""
        out = []
        for i in self.tree.query(footprint, predicate="intersects"):
            r = self.rows[i]
            if before and r["capture_date"] and r["capture_date"] >= before:
                continue
            overlap = self.polys[i].intersection(footprint).area / footprint.area
            if overlap > 0.01:
                out.append({**{k: r[k] for k in ("tile", "split", "name", "capture_date")}, "overlap": overlap, "_i": i})
        out.sort(key=lambda c: -c["overlap"])
        return out[:limit]

    def load(self, cand: dict):
        r = self.rows[cand["_i"]]
        rgb = cv2.cvtColor(cv2.imread(str(XBD / r["split"] / "images" / f"{r['name']}.png")), cv2.COLOR_BGR2RGB)
        return rgb, Affine.from_gdal(*r["gt"]), WGS84


@lru_cache(maxsize=1)
def xbd_archive() -> XBDArchive:
    return XBDArchive()
