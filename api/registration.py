"""Learned registration of the before image onto the after image.

Phase correlation (imagery.estimate_shift) only finds a translation. Real before/after captures also differ in
rotation and zoom (camera heading, altitude, a different sensor). Here sparse local features are detected with DISK
and matched with LightGlue (both learned, run through kornia; Apache-2.0), a similarity transform (shift, rotation,
zoom) is fitted to the matches with RANSAC, and it is accepted only when enough matches agree over enough of the
image. When the learned matcher is unavailable (no weights, no network on first use) or the images share too few
features, SIFT with the same fitting is tried, and the caller falls back to phase correlation.

Matching is done on a reduced copy (long side <= MAX_SIDE) for images up to about 1.25 x that size, and on up to 2 x 2
full-resolution windows of that size for larger ones; the transform is fitted in full-resolution pixels, so the rotation
estimate is good to about 0.05 degrees and the translation to about a pixel; a final phase-correlation step in the caller
removes what is left.
"""
import math
import threading
from dataclasses import asdict, dataclass

import cv2
import numpy as np
import torch

MAX_SIDE = 1280          # matching resolution (long side)
N_KEYPOINTS = 2048
RANSAC_PX = 3.0          # inlier tolerance at matching resolution (scaled back to full-resolution pixels)
MIN_INLIERS = 15
MIN_RATIO = 0.05         # inliers / matches; low on purpose: after a disaster most matches sit on ground that has changed
MIN_SPREAD = 0.15        # inlier hull area / image area: matches must not sit in one corner
SCALE_RANGE = (0.7, 1.4)
_lock = threading.Lock()
_models = {}


@dataclass
class Registration:
    ok: bool
    method: str                       # "disk+lightglue" or "sift"
    matches: int = 0
    inliers: int = 0
    rotation_deg: float = 0.0
    scale: float = 1.0
    shift_px: float = 0.0             # displacement of the image centre under the transform
    rms_px: float = 0.0               # inlier residual at full resolution
    matrix: list | None = None        # 2x3, maps before-image pixels (index coordinates) to after-image pixels
    reason: str = ""

    def info(self) -> dict:
        d = asdict(self)
        d.pop("matrix")
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def _learned():
    if "learned" not in _models:
        from kornia.feature import DISK, LightGlue
        _models["learned"] = (DISK.from_pretrained("depth").eval(), LightGlue("disk").eval())
    return _models["learned"]


def _gray(img, valid, scale):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if valid is not None:
        g = g * valid.astype(np.uint8)
    return cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else g


def _match_learned(a, b):
    disk, glue = _learned()
    tens = lambda g: torch.from_numpy(g).float().div(255)[None, None].repeat(1, 3, 1, 1)
    with torch.no_grad():
        fa, fb = (disk(tens(g), n=N_KEYPOINTS, pad_if_not_divisible=True)[0] for g in (a, b))
        size = lambda g: torch.tensor([[g.shape[1], g.shape[0]]], dtype=torch.float32)
        out = glue({"image0": {"keypoints": fa.keypoints[None], "descriptors": fa.descriptors[None], "image_size": size(a)},
                    "image1": {"keypoints": fb.keypoints[None], "descriptors": fb.descriptors[None], "image_size": size(b)}})
    m = out["matches"][0].cpu().numpy()
    return fa.keypoints.cpu().numpy()[m[:, 0]], fb.keypoints.cpu().numpy()[m[:, 1]]


def _match_sift(a, b):
    sift = cv2.SIFT_create(nfeatures=N_KEYPOINTS)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return np.zeros((0, 2)), np.zeros((0, 2))
    pairs = cv2.BFMatcher().knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
    return (np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 2),
            np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 2))


def _fit(pa, pb, shape, tol):
    """Similarity transform taking `pa` (before) to `pb` (after), both in full-resolution pixel coordinates; `tol` is the inlier
    tolerance in those pixels. Returns an accepted or a rejected Registration."""
    method = "disk+lightglue"
    n = len(pa)
    if n < MIN_INLIERS:
        return Registration(False, method, n, reason=f"only {n} matches")
    m, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=tol, maxIters=5000,
                                         confidence=0.999, refineIters=20)
    if m is None:
        return Registration(False, method, n, reason="no consistent transform")
    inl = inl.ravel().astype(bool)
    k = int(inl.sum())
    s = math.sqrt(abs(np.linalg.det(m[:, :2])))
    rot = math.degrees(math.atan2(m[1, 0], m[0, 0]))
    hull = cv2.contourArea(cv2.convexHull(pa[inl])) if k >= 3 else 0.0
    spread = hull / (shape[0] * shape[1])
    why = ("too few agreeing matches" if k < MIN_INLIERS else "matches disagree" if k / n < MIN_RATIO
           else "matches cover too little of the image" if spread < MIN_SPREAD
           else "implausible zoom" if not SCALE_RANGE[0] <= s <= SCALE_RANGE[1] else "")
    c = np.array([shape[1] / 2, shape[0] / 2])
    res = np.linalg.norm(pb[inl] - (pa[inl] @ m[:, :2].T + m[:, 2]), axis=1)
    return Registration(not why, method, n, k, rot, s, float(np.linalg.norm(m[:, :2] @ c + m[:, 2] - c)),
                        float(np.sqrt((res ** 2).mean())), m.tolist(), why)


def _windows(h, w, size=MAX_SIDE):
    """Matching windows (y, x, height, width) at full resolution: the whole image when it is not much larger than `size`,
    otherwise up to 2 x 2 windows of `size` spread over it, so that large images are matched at full resolution."""
    if max(h, w) <= size * 1.25:
        return [(0, 0, h, w)]
    ys = np.linspace(0, h - size, 2).astype(int) if h > size else [0]
    xs = np.linspace(0, w - size, 2).astype(int) if w > size else [0]
    return [(int(y), int(x), min(size, h), min(size, w)) for y in ys for x in xs]


def register(pre: np.ndarray, post: np.ndarray, valid: np.ndarray | None = None, methods=("learned", "sift")) -> Registration:
    """Transform that maps `pre` onto `post` (both uint8 RGB, same size). Tries each method in order, returns the first
    accepted result, or the last rejection (ok=False) so the caller can say why."""
    h, w = post.shape[:2]
    wins = _windows(h, w)
    last = Registration(False, "none", reason="no method available")
    for name in methods:
        pa_all, pb_all, failure = [], [], None
        for y0, x0, hh, ww in wins:
            scale = min(1.0, MAX_SIDE / max(hh, ww))
            vcrop = None if valid is None else valid[y0:y0 + hh, x0:x0 + ww]
            a, b = _gray(pre[y0:y0 + hh, x0:x0 + ww], vcrop, scale), _gray(post[y0:y0 + hh, x0:x0 + ww], None, scale)
            try:
                with _lock:
                    pa, pb = _match_learned(a, b) if name == "learned" else _match_sift(a, b)
            except Exception as e:  # noqa: BLE001  no weights / no network: fall through to the next method
                failure = f"{name} unavailable: {type(e).__name__}"
                break
            if vcrop is not None and len(pa):   # drop matches in the empty (uncovered) part of the before image
                vs = cv2.resize(vcrop.astype(np.uint8), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
                keep = vs[np.clip(pa[:, 1].astype(int), 0, a.shape[0] - 1), np.clip(pa[:, 0].astype(int), 0, a.shape[1] - 1)] > 0
                pa, pb = pa[keep], pb[keep]
            off = np.array([x0, y0], np.float32)
            pa_all.append(np.asarray(pa, np.float32).reshape(-1, 2) / scale + off)
            pb_all.append(np.asarray(pb, np.float32).reshape(-1, 2) / scale + off)
        if failure:
            last = Registration(False, name, reason=failure)
            continue
        scale = min(1.0, MAX_SIDE / max(wins[0][2], wins[0][3]))
        last = _fit(np.concatenate(pa_all), np.concatenate(pb_all), (h, w), RANSAC_PX / scale)
        last.method = "disk+lightglue" if name == "learned" else "sift"
        if last.ok:
            return last
    return last


def apply(reg: Registration, pre: np.ndarray, valid: np.ndarray):
    """Warp the before image and its valid mask with the fitted transform."""
    m = np.float32(reg.matrix)
    h, w = valid.shape
    return (cv2.warpAffine(pre, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=0),
            cv2.warpAffine(valid.astype(np.uint8), m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0).astype(bool))
