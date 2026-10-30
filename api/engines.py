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
REVIEW_CONFIDENCE = 0.6       # below this max class probability a building is flagged for review
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

    @torch.no_grad()
    def predict_maps(self, split, pair_id):
        from seg_benchmark import Pairs, XView2Score
        pre, post, loc_t, dmg_t, _ = Pairs([(split, pair_id)], train=False)[0]
        with _LOCK:
            loc_logit, dmg_logit = self.net(pre[None].to(self.device), post[None].to(self.device))
        loc = (torch.sigmoid(loc_logit[0]) > 0.5).cpu().numpy()
        dmg_prob = torch.softmax(dmg_logit[0], 0).cpu().numpy()          # 4 x H x W
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
                    dmg_p[:, y:y + wy, x:x + wx] += torch.softmax(d[0], 0).cpu().numpy()
                    hits[y:y + wy, x:x + wx] += 1
        return loc_p[:h, :w] / hits[:h, :w], dmg_p[:, :h, :w] / hits[:h, :w]

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


def load_engine(entry: dict, device="cpu"):
    return (ClassifierEngine if entry["kind"] == "classifier" else UNetEngine)(entry["run_dir"], device)


def class_name(i):
    return None if i is None else CLASS_NAMES[i]
