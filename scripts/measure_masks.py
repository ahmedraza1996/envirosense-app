"""Do the model's building masks follow the label frame (before image) or the after image, and is the offset one
shift per tile or local? Uses stored area assessments (damage-map PNG alpha = predicted building mask) of hold tiles.

  uv run --no-sync python app/scripts/measure_masks.py
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.api import snap  # noqa: E402

XBD = ROOT / "data/xbd/hold"
STORE = ROOT / "runs/app/assessments"
rows = []
for png in sorted(STORE.glob("*__area_damage.png")):
    pid, model = png.name.split("__")[0], png.name.split("__")[1]
    if not (XBD / "images" / f"{pid}_pre_disaster.png").exists():
        continue
    pred = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)[..., 3] > 0
    rd = lambda ph: cv2.cvtColor(cv2.imread(str(XBD / "images" / f"{pid}_{ph}_disaster.png")), cv2.COLOR_BGR2RGB)
    pre, post = rd("pre"), rd("post")
    lab = cv2.imread(str(XBD / "targets" / f"{pid}_post_disaster_target.png"), cv2.IMREAD_UNCHANGED) > 0
    if lab.mean() < 0.01 or pred.mean() < 0.01:
        continue
    e_pre, e_post = snap.edge_strength(pre), snap.edge_strength(post)
    r = {"pair": pid, "model": model}
    for name, m in (("pred", pred), ("label", lab)):
        for ph, e in (("pre", e_pre), ("post", e_post)):
            r[f"{name}_to_{ph}"] = snap.peak(snap.surface(m, e))[:3]
    # within-tile spread: label offset to the after image in each quadrant
    q = []
    for ys in (slice(0, 512), slice(512, 1024)):
        for xs in (slice(0, 512), slice(512, 1024)):
            mq = np.zeros_like(lab); mq[ys, xs] = lab[ys, xs]
            if mq.mean() > 0.01:
                q.append(snap.peak(snap.surface(mq, e_post))[:2])
    r["label_post_quadrants"] = q
    rows.append(r)
    print(pid, model, flush=True)
A = lambda k, i=None: np.array([x[k][:2] for x in rows])
out = {"n": len(rows)}
for k in ("pred_to_pre", "pred_to_post", "label_to_pre", "label_to_post"):
    v = A(k); out[k] = {"median_abs": float(np.median(np.hypot(*v.T))), "p90_abs": float(np.percentile(np.hypot(*v.T), 90))}
d = A("pred_to_post") - A("label_to_post")
out["pred_minus_label_to_post"] = {"median_abs": float(np.median(np.hypot(*d.T))), "p90_abs": float(np.percentile(np.hypot(*d.T), 90))}
spread = [np.std(np.array(r["label_post_quadrants"]), axis=0).mean() for r in rows if len(r["label_post_quadrants"]) >= 3]
out["within_tile_spread_px"] = {"n": len(spread), "median": float(np.median(spread)), "p90": float(np.percentile(spread, 90))}
print(json.dumps(out, indent=1))
(ROOT / "runs/app/mask_alignment.json").write_text(json.dumps({**out, "tiles": rows}, default=float, indent=1))
