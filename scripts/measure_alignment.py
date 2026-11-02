"""Where do the xBD label outlines sit: on the before image, on the after image, or neither?

For every hold tile with buildings the label mask is moved over a window of shifts and scored by the image edge strength
under its outline; the shift with the best score is where the picture's building edges really are. Reported in pixels
(1 px ~ 0.5 m): median, spread and share of tiles with a shift above 1 px, for the before and the after image, plus
the offset between the two images' own geotransforms. A pooled estimate across all tiles (summed score surfaces) is
the headline: single tiles with few buildings are noisy.

  uv run --no-sync python app/scripts/measure_alignment.py [--split hold] [--limit 0]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.api.imagery import estimate_shift  # noqa: E402
from app.api.scenes import geotransforms  # noqa: E402

XBD = ROOT / "data" / "xbd"
R = 12     # search window +-R px


def edge_strength(img):
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    return cv2.magnitude(gx, gy)


def surface(mask, edges):
    """Score for every integer shift (dy, dx) in [-R, R]: edge strength under the mask outline moved by that shift."""
    m = mask.astype(np.uint8)
    outline = (m - cv2.erode(m, np.ones((3, 3), np.uint8))).astype(np.float32)
    tpl = outline[R:-R, R:-R]
    res = cv2.matchTemplate(edges, tpl, cv2.TM_CCORR)
    return res / max(float(outline.sum()), 1.0)   # mean edge strength per outline pixel


def peak(s):
    """Sub-pixel (dx, dy) of the surface maximum by a parabola through its neighbours."""
    i, j = np.unravel_index(np.argmax(s), s.shape)
    def sub(a, b, c):
        d = a - 2 * b + c
        return 0.0 if d == 0 else 0.5 * (a - c) / d
    dy = sub(s[i - 1, j], s[i, j], s[i + 1, j]) if 0 < i < s.shape[0] - 1 else 0.0
    dx = sub(s[i, j - 1], s[i, j], s[i, j + 1]) if 0 < j < s.shape[1] - 1 else 0.0
    return j - R + dx, i - R + dy


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split", default="hold")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--every", type=int, default=1, help="use every n-th tile")
    a = p.parse_args()
    gts = geotransforms()
    pids = sorted(f.name[: -len("_pre_disaster.png")] for f in (XBD / a.split / "images").glob("*_pre_disaster.png"))
    rows, pooled = [], {k: 0 for k in ("pre", "post")}
    for pid in pids[::a.every][:a.limit or None]:
        pre = cv2.imread(str(XBD / a.split / "images" / f"{pid}_pre_disaster.png"))
        post = cv2.imread(str(XBD / a.split / "images" / f"{pid}_post_disaster.png"))
        lab = cv2.imread(str(XBD / a.split / "targets" / f"{pid}_post_disaster_target.png"), cv2.IMREAD_UNCHANGED) > 0
        if lab.mean() < 0.005:
            continue
        s_pre, s_post = surface(lab, edge_strength(pre)), surface(lab, edge_strength(post))
        pooled["pre"] = pooled["pre"] + s_pre
        pooled["post"] = pooled["post"] + s_post
        gp, gq = gts.get(f"{pid}_pre_disaster.png"), gts.get(f"{pid}_post_disaster.png")
        geo = None
        if gp and gq:
            geo = [(gp[0][0] - gq[0][0]) / gq[0][1], (gp[0][3] - gq[0][3]) / gq[0][5]]
        sh = estimate_shift(cv2.cvtColor(pre, cv2.COLOR_BGR2RGB), cv2.cvtColor(post, cv2.COLOR_BGR2RGB), np.ones(lab.shape, bool))
        lp = peak(s_post)
        # moving the label outline by -shift (pre -> post) should put it on the after image
        resid = [lp[0] + sh[0], lp[1] + sh[1]] if sh else None
        rows.append({"pair": pid, "label_to_pre": peak(s_pre), "label_to_post": lp, "pre_to_post_shift": sh and sh[:2],
                     "response": sh and sh[2], "label_to_post_after_shift": resid, "geo_pre_minus_post_px": geo})
    out = {"n_tiles": len(rows), "window_px": R}
    for k in ("pre", "post"):
        v = np.array([r[f"label_to_{k}"] for r in rows])
        out[f"label_to_{k}"] = {"median_dx": float(np.median(v[:, 0])), "median_dy": float(np.median(v[:, 1])),
                                "median_abs": float(np.median(np.hypot(*v.T))), "p90_abs": float(np.percentile(np.hypot(*v.T), 90)),
                                "share_over_1px": float((np.hypot(*v.T) > 1).mean()),
                                "pooled": [float(x) for x in peak(pooled[k])]}
    v = np.array([r["label_to_post_after_shift"] for r in rows if r["label_to_post_after_shift"]])
    out["label_to_post_after_shift"] = {"n": len(v), "median_abs": float(np.median(np.hypot(*v.T))), "p90_abs": float(np.percentile(np.hypot(*v.T), 90)),
                                        "share_over_1px": float((np.hypot(*v.T) > 1).mean())}
    sh = np.array([r["pre_to_post_shift"] for r in rows if r["pre_to_post_shift"]])
    out["pre_to_post_shift"] = {"median_abs": float(np.median(np.hypot(*sh.T))), "p90_abs": float(np.percentile(np.hypot(*sh.T), 90))}
    g = np.array([r["geo_pre_minus_post_px"] for r in rows if r["geo_pre_minus_post_px"]])
    if len(g):
        out["geotransform_pre_minus_post_px"] = {"median_dx": float(np.median(g[:, 0])), "median_dy": float(np.median(g[:, 1])),
                                                 "median_abs": float(np.median(np.hypot(*g.T)))}
    print(json.dumps(out, indent=2))
    (ROOT / "runs" / "app" / "alignment_measure.json").write_text(json.dumps({**out, "tiles": rows}, indent=1))


if __name__ == "__main__":
    main()
