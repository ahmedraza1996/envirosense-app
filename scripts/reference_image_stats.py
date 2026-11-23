"""Range of the input-quality statistics on xBD training images (1st to 99th percentile), written to governance/reference_image_stats.json.
An uploaded image whose statistics fall outside this range is flagged as unusual (api/input_quality.py).

  uv run --no-sync python -m app.scripts.reference_image_stats [--n 600]
"""
import argparse
import json
import random
from datetime import datetime, timezone

import cv2
import numpy as np

from app.api.engines import ROOT
from app.api.input_quality import REFERENCE, statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    files = sorted(p for s in ("train", "tier3") for p in (ROOT / "data" / "xbd" / s / "images").glob("*_post_disaster.png"))
    random.Random(a.seed).shuffle(files)
    rows = []
    for p in files[: a.n]:
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is not None:
            rgb = img[:, :, ::-1]
            rows.append(statistics(rgb, rgb.max(-1) > 0))     # as for uploads: pure-black padding is outside the image, not part of it
    keys = list(rows[0])
    ranges = {k: [round(float(np.percentile([r[k] for r in rows], 1)), 4), round(float(np.percentile([r[k] for r in rows], 99)), 4)] for k in keys}
    REFERENCE.write_text(json.dumps({"source": "xBD train + tier3 after images", "images": len(rows), "seed": a.seed, "percentiles": [1, 99],
                                     "made_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "ranges": ranges}, indent=2) + "\n")
    print(json.dumps(ranges, indent=2))


if __name__ == "__main__":
    main()
