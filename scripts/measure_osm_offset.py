"""Where do OpenStreetMap building outlines sit on an xBD tile, given the tile's geotransform?
The OSM outlines of a tile (Overpass JSON, `way["building"]; out geom;`) are drawn into the image grid and moved over a window of
shifts; the shift that puts them on the strongest image edges is the offset between the street map and the imagery (OSM outlines
were traced on other imagery, so a metre or two is expected from that alone).

  uv run --no-sync python app/scripts/measure_osm_offset.py <overpass.json> <pair_id> [split]
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.api import snap  # noqa: E402
from app.api.scenes import geotransforms, pixel_size_m  # noqa: E402

js, pid = json.loads(Path(sys.argv[1]).read_text()), sys.argv[2]
split = sys.argv[3] if len(sys.argv) > 3 else "hold"
gt = geotransforms()[f"{pid}_post_disaster.png"][0]
px = lambda lon, lat: ((lon - gt[0]) / gt[1], (lat - gt[3]) / gt[5])       # north-up geotransform
mask = np.zeros((1024, 1024), np.uint8)
n = 0
for el in js["elements"]:
    pts = np.array([px(p["lon"], p["lat"]) for p in el.get("geometry", [])])
    if len(pts) >= 3:
        cv2.fillPoly(mask, [np.round(pts * 16).astype(np.int32)], 1, shift=4)
        n += 1
print(pid, "OSM buildings drawn:", n, "coverage", round(float(mask.mean()), 3), "pixel", round(pixel_size_m(pid), 3), "m")
R = 40
for ph in ("pre", "post"):
    img = cv2.cvtColor(cv2.imread(str(ROOT / "data/xbd" / split / "images" / f"{pid}_{ph}_disaster.png")), cv2.COLOR_BGR2RGB)
    s = snap.surface(mask.astype(bool), snap.edge_strength(img), R)
    dx, dy, sharp = snap.peak(s, R)
    print(f"  OSM outlines -> {ph} image: move by dx {dx:+.1f} px, dy {dy:+.1f} px = {np.hypot(dx, dy) * pixel_size_m(pid):.1f} m (peak sharpness {sharp:.2f})")

# Mask-to-OSM: overlap (IoU) of the model's building mask with the OSM outlines over a window of shifts
if len(sys.argv) > 4:
    pred = cv2.imread(sys.argv[4], cv2.IMREAD_UNCHANGED)[..., 3] > 0
    for name, other in (("model mask", pred), ("xBD labels", cv2.imread(str(ROOT / "data/xbd" / split / "targets" / f"{pid}_post_disaster_target.png"), cv2.IMREAD_UNCHANGED) > 0)):
        best = (-1, 0, 0)
        scores = np.zeros((2 * R + 1, 2 * R + 1))
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                m = np.roll(np.roll(mask.astype(bool), dy, 0), dx, 1)
                inter = (m & other).sum()
                scores[dy + R, dx + R] = inter / max((m | other).sum(), 1)
        i, j = np.unravel_index(scores.argmax(), scores.shape)
        print(f"  {name} vs OSM outlines: best overlap IoU {scores.max():.2f} when OSM is moved by dx {j - R:+d} px, dy {i - R:+d} px "
              f"({np.hypot(j - R, i - R) * pixel_size_m(pid):.1f} m); at no shift IoU {scores[R, R]:.2f}")
