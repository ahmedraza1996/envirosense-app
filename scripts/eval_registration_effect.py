"""Does registration give the damage score back? (proposal experiment X6)

Hold split, every 6th pair (156 tiles, as in src/robustness.py): the before image is shifted, rotated or zoomed by a known
amount; then one of three strategies is applied before inference and the xView2 score is computed against the unchanged labels:

  none               the moved before image is used as it is
  phase correlation  translation only (src/align.py, what the app used before learned registration)
  learned            the app's upload pipeline: DISK + LightGlue (SIFT fallback) similarity transform, then a residual
                     phase-correlation shift; when registration is declined only the shift step runs

Every condition is also run on the unmoved pair, to see whether registration hurts pairs that need none.
Step 1 computes the learned transforms once (GPU optional) and caches them; step 2 scores each model.

  REGISTRATION_DEVICE=cuda:1 uv run --no-sync python app/scripts/eval_registration_effect.py \
      --run S_r34_paired_ext --run S_r34_paired_mis --gpu 1
"""
import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("TORCH_HOME", str(ROOT / ".cache" / "torch"))
import cv2, numpy as np, torch  # noqa: E402

import seg_benchmark  # noqa: E402
from align import align_pre  # noqa: E402
from app.api import imagery, registration as R, uploads  # noqa: E402
from seg_benchmark import MEAN, STD, XBD, Pairs, SiameseUNet, evaluate, list_pairs  # noqa: E402

CONDITIONS = [("unmoved pair", {}), ("shift 16 px (8 m)", dict(dx=16)), ("shift 32 px (16 m)", dict(dx=32)),
              ("rotate 2 deg", dict(deg=2)), ("rotate 5 deg", dict(deg=5)), ("zoom 3%", dict(scale=1.03)),
              ("rotate 3 deg + zoom 3% + shift 22 px", dict(deg=3, scale=1.03, dx=22, dy=-10))]
CACHE = ROOT / "runs" / "tmp" / "registration_effect" / "transforms.json"


def move(img, dx=0.0, dy=0.0, deg=0.0, scale=1.0):
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, scale)
    m[:, 2] += (dx, dy)
    return cv2.warpAffine(np.ascontiguousarray(img), m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def read(pid, split, name):
    return cv2.imread(str(XBD / split / "images" / f"{pid}_{name}_disaster.png"), cv2.IMREAD_COLOR)[:, :, ::-1]


def learned_pipeline(pre, post):
    """The upload pipeline's registration step. Returns the corrected pre image and a record that reproduces it."""
    valid = np.ones(post.shape[:2], bool)
    rec = {"ok": False, "matrix": None, "shift": None, "info": None}
    reg = R.register(pre, post, valid)
    rec["info"] = reg.info()
    if reg.ok:
        significant = (abs(reg.rotation_deg) >= uploads.ROT_MIN_DEG or abs(reg.scale - 1) >= uploads.SCALE_MIN
                       or reg.shift_px >= uploads.SHIFT_MIN_PX)
        if significant and reg.shift_px <= uploads.SHIFT_MAX_PX * 4:
            pre, valid = R.apply(reg, pre, valid)
            rec["ok"], rec["matrix"] = True, reg.matrix
    est = imagery.estimate_shift(pre, post, valid)
    if est and est[2] >= uploads.MIN_RESPONSE:
        dx, dy, _ = est
        if uploads.SHIFT_MIN_PX <= np.hypot(dx, dy) <= uploads.SHIFT_MAX_PX:
            pre, valid = imagery.shift_image(pre, valid, dx, dy)
            rec["shift"] = [float(dx), float(dy)]
    return pre, rec


def replay(pre, rec):
    """Reproduce learned_pipeline's correction from a cached record (no matching needed)."""
    valid = np.ones(pre.shape[:2], bool)
    if rec["ok"]:
        pre, valid = R.apply(R.Registration(True, "cached", matrix=rec["matrix"]), pre, valid)
    if rec["shift"]:
        pre, valid = imagery.shift_image(pre, valid, *rec["shift"])
    return pre


def compute_transforms(items):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    t0, n = time.time(), 0
    for split, pid in items:
        post, pre0 = read(pid, split, "post"), read(pid, split, "pre")
        for name, cond in CONDITIONS:
            key = f"{pid}|{name}"
            if key in cache:
                continue
            _, rec = learned_pipeline(move(pre0, **cond), post)
            cache[key] = rec
            n += 1
            if n % 25 == 0:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache))
                print(f"  {n} registrations, {time.time() - t0:.0f}s", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))
    return cache


class Strategy(Pairs):
    cond, strategy, cache = {}, "none", {}

    def __getitem__(self, i):
        split, pid = self.items[i]
        load = lambda n, flag=cv2.IMREAD_COLOR: cv2.imread(str(XBD / split / n), flag)
        pre, post = read(pid, split, "pre"), read(pid, split, "post")
        loc = load(f"targets/{pid}_pre_disaster_target.png", cv2.IMREAD_UNCHANGED)
        dmg = load(f"targets/{pid}_post_disaster_target.png", cv2.IMREAD_UNCHANGED)
        pre = move(pre, **self.cond[1])
        if self.strategy == "phase correlation":
            pre, _ = align_pre(pre, post)
        elif self.strategy == "learned":
            pre = replay(pre, self.cache[f"{pid}|{self.cond[0]}"])
        norm = lambda a: torch.from_numpy(((np.asarray(a, np.float32) - MEAN) / STD).transpose(2, 0, 1).copy())
        return norm(pre), norm(post), torch.from_numpy((loc > 0).astype(np.float32)), torch.from_numpy(dmg.astype(np.int64)), pid


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", action="append", default=[])
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--gpu-mem-frac", type=float, default=0.6)
    p.add_argument("--tiles-step", type=int, default=6)
    a = p.parse_args()
    dev = torch.device(f"cuda:{a.gpu}")
    torch.cuda.set_per_process_memory_fraction(a.gpu_mem_frac, dev)
    items = list_pairs("hold")[:: a.tiles_step]
    print(f"{len(items)} tiles, {len(CONDITIONS)} conditions; registration device {R.DEVICE}", flush=True)
    cache = compute_transforms(items)
    ok = sum(v["ok"] for v in cache.values())
    print(f"registration accepted for {ok} of {len(cache)} moved pairs", flush=True)
    seg_benchmark.Pairs = Strategy
    Strategy.cache = cache
    for run in a.run or ["S_r34_paired_ext", "S_r34_paired_mis"]:
        ck = torch.load(ROOT / "runs" / run / "best.pt", map_location="cpu", weights_only=False)
        net = SiameseUNet(ck["args"]["encoder"], mode=ck["args"]["mode"])
        net.load_state_dict(ck["model"])
        net = net.to(dev).eval()
        out = []
        with torch.no_grad():
            for name, cond in CONDITIONS:
                for strat in ("none", "phase correlation", "learned"):
                    Strategy.cond, Strategy.strategy = (name, cond), strat
                    r = evaluate(net, items, dev, 2)
                    out.append({"condition": name, "strategy": strat, **{k: float(v) for k, v in r.items()}})
                    print(f"{run:18s} {name:40s} {strat:18s} score {r['score']:.3f} loc {r['loc_f1']:.3f} dmg {r['dmg_f1']:.3f}", flush=True)
        acc = {}
        for k, v in cache.items():
            c = k.split("|")[1]
            acc.setdefault(c, []).append(bool(v["ok"]))
        (ROOT / "runs" / run / "registration_effect.json").write_text(json.dumps(
            {"n_pairs": len(items), "registration_accepted": {c: round(sum(v) / len(v), 3) for c, v in acc.items()}, "results": out}, indent=2))
        del net
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
