"""How well does registration recover a known misalignment? Hold tiles (urban ones, spread over all events): the before image is
moved by a known transform; registration is run on the moved and on the original pair. The error is the distance, at the four
corners, between the transform found for the moved pair and the one found for the original pair composed with the inverse of
the injected move. The original pair's own (unknown) registration cancels out, so this measures repeatability, not absolute
accuracy. Compared with phase correlation (translation only), which is what the app used before.

  uv run --no-sync python app/scripts/eval_registration.py [--tiles 24]
"""
import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TORCH_HOME", str(ROOT / ".cache" / "torch"))
import cv2, numpy as np, torch  # noqa: E402

torch.set_num_threads(2)
from app.api import imagery, registration as R  # noqa: E402
from app.api.scenes import catalogue  # noqa: E402

CONDITIONS = [("shift 16 px (8 m)", dict(dx=16)), ("shift 48 px (24 m)", dict(dx=48, dy=-20)), ("rotate 2 deg", dict(deg=2)),
              ("rotate 5 deg", dict(deg=5)), ("zoom 3%", dict(scale=1.03)),
              ("rotate 3 deg + zoom 3% + shift 22 px", dict(deg=3, scale=1.03, dx=22, dy=-10)), ("rotate 15 deg", dict(deg=15))]


def move(img, dx=0, dy=0, deg=0, scale=1.0):
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, scale)
    m[:, 2] += (dx, dy)
    return cv2.warpAffine(np.ascontiguousarray(img), m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), m


def mat3(m):
    m = np.asarray(m, np.float64)
    return m if m.shape == (3, 3) else np.vstack([m, [0, 0, 1]])


def corner_err(a, b, n=1024):
    pts = np.float64([[0, 0, 1], [n, 0, 1], [n, n, 1], [0, n, 1]]).T
    return float(np.linalg.norm((mat3(a) @ pts - mat3(b) @ pts)[:2], axis=0).mean())


def phase_matrix(pre, post):
    est = imagery.estimate_shift(pre, post, np.ones(post.shape[:2], bool))
    return None if est is None or est[2] < 0.05 else np.array([[1, 0, -est[0]], [0, 1, -est[1]]], np.float64)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tiles", type=int, default=24)
    a = p.parse_args()
    cat = catalogue()
    cat = cat[(cat.split == "hold") & (cat.buildings >= 40)].sort_values("pair_id")
    pids = cat.pair_id.iloc[np.linspace(0, len(cat) - 1, a.tiles).round().astype(int)].tolist()
    rd = lambda pid, ph: cv2.cvtColor(cv2.imread(str(ROOT / "data/xbd/hold/images" / f"{pid}_{ph}_disaster.png")), cv2.COLOR_BGR2RGB)
    rows = []
    for pid in pids:
        pre, post = rd(pid, "pre"), rd(pid, "post")
        ref = R.register(pre, post, None)
        ref_pc = phase_matrix(pre, post)
        row = {"pair": pid, "natural_ok": ref.ok, "natural_inliers": ref.inliers, "conditions": {}}
        for name, kw in CONDITIONS:
            t = time.time()
            moved, m = move(pre, **kw)
            inv = mat3(cv2.invertAffineTransform(m))
            reg = R.register(moved, post, None)
            c = {"learned_ok": reg.ok, "learned_method": reg.method, "inliers": reg.inliers, "sec": round(time.time() - t, 1)}
            if reg.ok and ref.ok:
                c["learned_err_px"] = corner_err(reg.matrix, mat3(ref.matrix) @ inv)
            pm = phase_matrix(moved, post)
            if pm is not None and ref_pc is not None:
                c["phase_err_px"] = corner_err(pm, mat3(ref_pc) @ inv)
            row["conditions"][name] = c
        rows.append(row)
        print(pid, "natural", ref.ok, ref.inliers, {k: (round(v.get("learned_err_px", -1), 2), round(v.get("phase_err_px", -1), 1)) for k, v in row["conditions"].items()}, flush=True)
    out = {"n_tiles": len(rows), "natural_registered": sum(r["natural_ok"] for r in rows), "conditions": {}}
    for name, _ in CONDITIONS:
        cs = [r["conditions"][name] for r in rows]
        good = lambda c, k: k in c and c[k] < 2.0
        out["conditions"][name] = {
            "learned_accepted": sum(c["learned_ok"] for c in cs), "learned_within_2px": sum(good(c, "learned_err_px") for c in cs),
            "learned_median_err_px": float(np.median([c["learned_err_px"] for c in cs if "learned_err_px" in c])) if any("learned_err_px" in c for c in cs) else None,
            "phase_within_2px": sum(good(c, "phase_err_px") for c in cs),
            "phase_median_err_px": float(np.median([c["phase_err_px"] for c in cs if "phase_err_px" in c])) if any("phase_err_px" in c for c in cs) else None}
    print(json.dumps(out, indent=1))
    (ROOT / "runs/app/registration_eval.json").write_text(json.dumps({**out, "tiles": rows}, indent=1, default=float))


if __name__ == "__main__":
    main()
