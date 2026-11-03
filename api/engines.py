"""Inference engines for the app. Both reuse the training code paths, so the app runs the same models and
preprocessing as the reported results (checked by app/tests/test_engines.py).

ClassifierEngine: per-building crop classifier (model A post-only / B paired) from src/train.py runs.
UNetEngine:       full-image U-Net (post / early / paired) from src/seg_benchmark.py runs.
Inference runs on CPU by default with few threads, so it never competes with training for the GPUs.
"""
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("TORCH_HOME", str(ROOT / ".cache" / "torch"))
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

import build_crops  # noqa: E402
from data import CLASS_NAMES, CropConfig, model_input  # noqa: E402
from models import Paired, PostOnly  # noqa: E402

XBD = ROOT / "data" / "xbd"
LABEL_IDS = {"no-damage": 0, "minor-damage": 1, "major-damage": 2, "destroyed": 3}
MIN_LOCALIZED = 0.2           # U-Net: share of the footprint that must be predicted as building
_LOCK = threading.Lock()      # one inference at a time: the app never stacks jobs on the server

torch.set_num_threads(int(os.environ.get("APP_TORCH_THREADS", "2")))


def read_rgb(split, pair_id, phase):
    return cv2.cvtColor(cv2.imread(str(XBD / split / "images" / f"{pair_id}_{phase}_disaster.png")), cv2.COLOR_BGR2RGB)


def run_info(run_dir: Path) -> dict:
    cfg = json.loads((run_dir / "config.json").read_text()) if (run_dir / "config.json").exists() else {}
    return {"run": run_dir.name, "checkpoint": str((run_dir / "best.pt").relative_to(ROOT)),
            "git_commit": cfg.get("git_commit") or "not recorded (run predates provenance logging)"}


class ClassifierEngine:
    kind = "classifier"

    def __init__(self, run_dir: Path, device="cpu"):
        ck = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=False)
        a = ck["args"]
        self.cfg = CropConfig(a["context"], a["floor"], a["size"], not a["no_mask"])
        self.paired = a["model"] == "paired"
        in_ch = 4 if self.cfg.use_mask else 3
        net = Paired(a["arch"], in_ch, a["fusion"], pretrained=False) if self.paired else PostOnly(a["arch"], in_ch, pretrained=False)
        net.load_state_dict(ck["model"])
        self.net, self.device = net.to(device).eval(), torch.device(device)
        self.mode = "paired (pre + post)" if self.paired else "post-only"
        self.info = {**run_info(run_dir), "epoch": ck.get("epoch"), "arch": a["arch"]}

    @torch.no_grad()
    def assess(self, split, pair_id, batch=128):
        """One record per building in the post label: probabilities over the 4 damage classes."""
        pre, post = read_rgb(split, pair_id, "pre"), read_rgb(split, pair_id, "post")
        feats = build_crops.read_features(split, pair_id)
        items, keep = [], []
        for i, (uid, sub, polys, invalid) in enumerate(feats):
            if not polys:
                continue
            x, y, w, side = build_crops.window(polys)
            inp = model_input(build_crops.crop(post, x, y, w), build_crops.crop(pre, x, y, w),
                              build_crops.mask(polys, x, y, w), np.float32(side), np.float32(w),
                              self.cfg, build_crops.STORE_SIZE, self.paired)
            items.append(inp)
            keep.append(i)
        probs = []
        with _LOCK:
            for s in range(0, len(items), batch):
                chunk = items[s:s + batch]
                post_t = torch.stack([c["post"] for c in chunk]).to(self.device)
                pre_t = torch.stack([c["pre"] for c in chunk]).to(self.device) if self.paired else None
                probs.append(torch.softmax(self.net(post_t, pre_t), 1).cpu().numpy())
        probs = np.concatenate(probs) if probs else np.zeros((0, 4), np.float32)
        out = []
        for j, i in enumerate(keep):
            uid, sub, polys, invalid = feats[i]
            p = probs[j]
            out.append({"uid": uid, "polys": polys, "true_subtype": sub, "probs": p.tolist(),
                        "predicted": int(p.argmax()), "confidence": float(p.max()), "invalid_polygon": invalid})
        return {"buildings": out, "scene_metrics": {}}


class UNetEngine:
    kind = "unet"

    def __init__(self, run_dir: Path, device="cpu"):
        from seg_benchmark import SiameseUNet  # imported lazily: pulls in segmentation_models_pytorch
        ck = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=False)
        a = ck["args"]
        net = SiameseUNet(a["encoder"], mode=a["mode"])
        net.load_state_dict(ck["model"])
        self.net, self.device = net.to(device).eval(), torch.device(device)
        self.mode = {"post": "post-only", "early": "pre + post (early fusion)", "paired": "pre + post (Siamese)"}[a["mode"]]
        self.info = {**run_info(run_dir), "epoch": ck.get("epoch"), "arch": a["encoder"]}
        cal = run_dir / "calibration.json"           # temperature scaling of the damage head (src/calibrate.py); argmax is unchanged
        c = json.loads(cal.read_text()) if cal.exists() else {}
        self.temperature = float(c["temperature"]) if c.get("apply") else 1.0       # applied only when it improves calibration
        self.info["temperature"] = self.temperature

    @torch.no_grad()
    def predict_maps(self, split, pair_id):
        from seg_benchmark import Pairs, XView2Score
        pre, post, loc_t, dmg_t, _ = Pairs([(split, pair_id)], train=False)[0]
        with _LOCK:
            loc_logit, dmg_logit = self.net(pre[None].to(self.device), post[None].to(self.device))
        loc = (torch.sigmoid(loc_logit[0]) > 0.5).cpu().numpy()
        dmg_prob = torch.softmax(dmg_logit[0] / self.temperature, 0).cpu().numpy()          # 4 x H x W
        dmg = (dmg_prob.argmax(0) + 1).astype(np.uint8) * loc             # 0 background, 1-4 damage
        sc = XView2Score()
        sc.add(loc, dmg, loc_t.numpy(), dmg_t.numpy())
        return loc, dmg, dmg_prob, sc.result()

    @property
    def uses_pre(self):
        return self.net.mode != "post"

    @torch.no_grad()
    def predict_large(self, pre_rgb: np.ndarray, post_rgb: np.ndarray, win: int = 1024, overlap: int = 128):
        """Image pair of any size (uint8 RGB on the same pixel grid): overlapping windows of the training tile size,
        probabilities averaged where windows overlap. Returns building probability (H x W), damage probs (4 x H x W).
        A single 1024 tile gives exactly the predict_maps result."""
        from seg_benchmark import MEAN, STD
        h, w = post_rgb.shape[:2]
        H, W = -(-h // 32) * 32, -(-w // 32) * 32                       # U-Net needs multiples of 32
        pad = lambda a: np.pad(a, ((0, H - h), (0, W - w), (0, 0)))
        norm = lambda a: torch.from_numpy(((a.astype(np.float32) - MEAN) / STD).transpose(2, 0, 1).copy())
        pre_t, post_t = norm(pad(pre_rgb)), norm(pad(post_rgb))
        wy, wx = min(win, H), min(win, W)
        starts = lambda n, k: sorted(set(list(range(0, n - k, k - overlap)) + [n - k]))
        loc_p = np.zeros((H, W), np.float32)
        dmg_p = np.zeros((4, H, W), np.float32)
        hits = np.zeros((H, W), np.float32)
        with _LOCK:
            for y in starts(H, wy):
                for x in starts(W, wx):
                    sl = (slice(None), slice(y, y + wy), slice(x, x + wx))
                    l, d = self.net(pre_t[sl][None].to(self.device), post_t[sl][None].to(self.device))
                    loc_p[y:y + wy, x:x + wx] += torch.sigmoid(l[0]).cpu().numpy()
                    dmg_p[:, y:y + wy, x:x + wx] += torch.softmax(d[0] / self.temperature, 0).cpu().numpy()
                    hits[y:y + wy, x:x + wx] += 1
        return loc_p[:h, :w] / hits[:h, :w], dmg_p[:, :h, :w] / hits[:h, :w]

    @torch.no_grad()
    def predict_stream(self, pre_rgb, post_rgb, valid=None, fallback=None, win=1024, overlap=128, progress=None):
        """predict_large for images of any size: windows are processed in horizontal bands and each finished band is
        stored as uint8 (probability x 255), so memory stays at a few hundred MB for a 8000 px image. The average over
        overlapping windows is the same as predict_large's. `valid` (before-image coverage) with a post-only `fallback`
        engine: windows with no coverage use the fallback, partly covered windows use both and take the fallback's
        output where the before image is missing. Returns building probability (H x W) and damage probabilities
        (4 x H x W), both uint8."""
        from seg_benchmark import MEAN, STD
        h, w = post_rgb.shape[:2]
        wy, wx = min(win, -(-h // 32) * 32), min(win, -(-w // 32) * 32)
        starts = lambda n, k: [0] if n <= k else sorted(set(range(0, n - k, k - overlap)) | {n - k})
        ys, xs = starts(h, wy), starts(w, wx)
        norm = lambda a: torch.from_numpy(((np.pad(a, ((0, wy - a.shape[0]), (0, wx - a.shape[1]), (0, 0))).astype(np.float32)
                                           - MEAN) / STD).transpose(2, 0, 1).copy())[None]
        out_loc, out_dmg = np.zeros((h, w), np.uint8), np.zeros((4, h, w), np.uint8)
        acc_loc, acc_dmg, hits = (np.zeros((wy, w), np.float32), np.zeros((4, wy, w), np.float32), np.zeros((wy, w), np.float32))
        done, total = 0, len(ys) * len(xs)

        def run(eng, pre_t, post_t):
            l, d = eng.net(pre_t.to(eng.device), post_t.to(eng.device))
            return torch.sigmoid(l[0]).cpu().numpy(), torch.softmax(d[0] / self.temperature, 0).cpu().numpy()

        for bi, y in enumerate(ys):
            for x in xs:
                post_t = norm(post_rgb[y:y + wy, x:x + wx])
                cover = 1.0 if valid is None else float(valid[y:y + wy, x:x + wx].mean())
                with _LOCK:
                    if fallback is None or cover > 0.999:
                        l, d = run(self, norm(pre_rgb[y:y + wy, x:x + wx]), post_t)
                    elif cover < 0.001:
                        l, d = run(fallback, post_t, post_t)
                    else:
                        l, d = run(self, norm(pre_rgb[y:y + wy, x:x + wx]), post_t)
                        lf, df = run(fallback, post_t, post_t)
                        v = np.pad(valid[y:y + wy, x:x + wx], ((0, wy - min(wy, h - y)), (0, wx - min(wx, w - x))))
                        l, d = np.where(v, l, lf), np.where(v, d, df)
                ch, cw = min(wy, h - y), min(wx, w - x)
                acc_loc[:ch, x:x + cw] += l[:ch, :cw]
                acc_dmg[:, :ch, x:x + cw] += d[:, :ch, :cw]
                hits[:ch, x:x + cw] += 1
                done += 1
                if progress:
                    progress(done, total)
            last = bi == len(ys) - 1
            end = h if last else ys[bi + 1]              # rows below `end` are still to be covered by the next band
            n = end - y
            q = lambda a: np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
            out_loc[y:end] = q(acc_loc[:n] / hits[:n])
            out_dmg[:, y:end] = q(acc_dmg[:, :n] / hits[:n])
            if not last:
                keep = y + wy - end
                for a in (acc_loc, acc_dmg, hits):
                    a[..., :keep, :] = a[..., n:n + keep, :].copy()
                    a[..., keep:, :] = 0
        return out_loc, out_dmg

    def assess(self, split, pair_id):
        loc, dmg, dmg_prob, scene_score = self.predict_maps(split, pair_id)
        out = []
        for uid, sub, polys, invalid in build_crops.read_features(split, pair_id):
            if not polys:
                continue
            m = np.zeros(loc.shape, np.uint8)
            for p in polys:
                cv2.fillPoly(m, [np.round(np.asarray(p.exterior.coords) * 16).astype(np.int32)], 1, shift=4)
            inside = m.astype(bool)
            if not inside.any():
                continue
            frac = float(loc[inside].mean())
            sel = inside & loc if frac >= MIN_LOCALIZED else inside
            p = dmg_prob[:, sel].mean(1)
            detected = frac >= MIN_LOCALIZED
            out.append({"uid": uid, "polys": polys, "true_subtype": sub, "probs": p.tolist(),
                        "predicted": int(np.bincount(dmg[sel] - 1, minlength=4).argmax()) if detected else None,
                        "confidence": float(p.max()), "localized_fraction": frac, "invalid_polygon": invalid})
        return {"buildings": out, "scene_metrics": {"xview2": scene_score}, "damage_map": dmg}


def discover_models() -> dict:
    """Model registry: only checkpoints that exist on disk."""
    spec = [
        ("clf_B", "Crop classifier B (pre + post)", "classifier", "B_r18_official"),
        ("clf_A", "Crop classifier A (post only)", "classifier", "A_r18_official"),
        ("unet_paired_mis", "Siamese U-Net, trained with misaligned pairs (pre + post)", "unet", "S_r34_paired_mis"),
        ("unet_paired_ext", "Siamese U-Net, 80 epochs (pre + post)", "unet", "S_r34_paired_ext"),
        ("unet_paired", "Siamese U-Net, 40 epochs (pre + post)", "unet", "S_r34_paired"),
        ("unet_early", "Full-image U-Net (pre + post, early fusion)", "unet", "S_r34_early"),
        ("unet_post", "Full-image U-Net (post only)", "unet", "S_r34_post"),
    ]
    found = {}
    for mid, label, kind, run in spec:
        d = ROOT / "runs" / run
        if (d / "best.pt").exists() and (kind != "unet" or (d / "test_metrics.json").exists()):
            score = None
            if (d / "test_metrics.json").exists():  # official xView2 score on the test split, used to pick the default
                score = json.loads((d / "test_metrics.json").read_text()).get("test", {}).get("score")
            found[mid] = {"id": mid, "label": label, "kind": kind, "run_dir": d, "test_score": score}
    return found


APPROVED = Path(__file__).resolve().parents[1] / "governance" / "approved_model.json"


def approved_default(models: dict) -> str | None:
    """Model id approved as the default for area alerts and uploads (sem.model_versions, one row has status 'approved'). The default is never
    chosen silently from test scores: without an approval, or when the approved model cannot be loaded here, there is none and the
    interface falls back to the best test score only for display."""
    from ..db import semantic
    mid = semantic.approved_id()
    return mid if mid in models else None


def review_confidence() -> float:
    """Below this highest class probability a structure is flagged for review (sem.thresholds; E17: 0.7 keeps ~59% of building pixels at 4-6% error)."""
    from ..db import semantic
    return semantic.threshold("review_confidence")


def load_engine(entry: dict, device="cpu"):
    return (ClassifierEngine if entry["kind"] == "classifier" else UNetEngine)(entry["run_dir"], device)


def class_name(i):
    return None if i is None else CLASS_NAMES[i]
