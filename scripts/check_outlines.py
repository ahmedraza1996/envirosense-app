"""Do the stored structure outlines reproduce the predicted building mask? Rasterise every outline at 1/16 px precision under the
pixel-edge convention (pixel i covers [i, i + 1]) and compare with the mask the outlines came from (damage-map alpha).
Also with the outlines moved by half a pixel, which is what the earlier pixel-centre outlines amounted to.

  uv run --no-sync python app/scripts/check_outlines.py <assessment id>
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parents[2]
store = ROOT / "runs/app/assessments"
aid = sys.argv[1]
rec = json.loads((store / f"{aid}.json").read_text())
mask = cv2.imread(str(store / f"{aid}_damage.png"), cv2.IMREAD_UNCHANGED)[..., 3] > 0
h, w = mask.shape

def raster(offset):
    """cv2 treats integer coordinates as pixel centres; stored outlines use pixel edges, so subtract half a pixel first."""
    m = np.zeros((h, w), np.uint8)
    for f in rec["features"]:
        ring = np.array(f["geometry"]["coordinates"][0]) - 0.5 + offset
        cv2.fillPoly(m, [np.round(ring * 16).astype(np.int32)], 1, shift=4)
    return m.astype(bool)

print(f"{len(rec['features'])} structures, mask covers {mask.mean():.1%} of the tile")
for name, off in (("outlines as stored", 0.0), ("outlines moved 0.5 px (the old pixel-centre error)", 0.5)):
    r = raster(off)
    print(f"{name:52s} IoU with the mask {(r & mask).sum() / (r | mask).sum():.3f}   centroid offset: "
          f"dx {np.nonzero(r)[1].mean() - np.nonzero(mask)[1].mean():+.2f} px, dy {np.nonzero(r)[0].mean() - np.nonzero(mask)[0].mean():+.2f} px")
