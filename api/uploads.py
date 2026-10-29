"""Uploaded imagery -> area alerts.

One job at a time, on CPU, in a background thread:
  1 read the after image (GeoTIFF, or PNG/JPEG with corner coordinates); resample to the training resolution if needed
  2 before image: the user's own, or found in the archive by location (captured before the event date when one is
    given); archive tiles are mosaicked onto the after image's pixel grid
  3 alignment check: phase correlation measures any remaining shift; small shifts are corrected; coverage is recorded
  4 the U-Net locates buildings and classifies damage: before + after wherever a before image covers the ground,
    after only elsewhere (the post-only model), so a partial before image never blocks the assessment
  5 structures and area alerts, exactly as for benchmark tiles
Each upload lives in runs/app/uploads/<id>/ (inputs, aligned before/after JPEGs, meta, status); the assessment record
goes to the shared assessment store, so maps, crops and reports work unchanged.
"""
import json
import math
import queue
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from rasterio.transform import Affine

from . import imagery, service
from .archive import xbd_archive
from .engines import ROOT

UPLOADS = ROOT / "runs" / "app" / "uploads"
EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")
MAX_BYTES = 300 * 2 ** 20
MAX_SIDE = 4096              # px after resampling (about 2 km at 0.5 m): bounds CPU time and memory
TARGET_M = 0.5               # metres per pixel used when an image is far from the training resolution
KEEP_M = (0.25, 0.9)         # xBD tiles are roughly 0.3-0.6 m per pixel; inside this range the image is used as is
COARSE_M = 1.2               # beyond this, damage classes are unreliable (noted on the record)
SHIFT_MIN_PX, SHIFT_MAX_PX, MIN_RESPONSE = 1.5, 48, 0.05   # response: phase-correlation peak
DISASTER_TYPES = ("earthquake", "fire", "flooding", "wind", "tsunami", "volcano", "other")

_queue: "queue.Queue[str]" = queue.Queue()
_active: set = set()
_worker = None


def is_upload(key: str) -> bool:
    return key.startswith("upl_")


def folder(uid: str) -> Path:
    if not re.fullmatch(r"upl_[0-9a-f]{8}", uid):
        raise KeyError(uid)
    return UPLOADS / uid


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def set_status(uid: str, **kw):
    path = folder(uid) / "status.json"
    st = {**read_json(path, {}), **kw, "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    path.write_text(json.dumps(st))
    return st


def info(uid: str) -> dict:
    d = folder(uid)
    if not (d / "meta.json").exists():
        raise KeyError(uid)
    st = read_json(d / "status.json", {})
    if st.get("state") in ("queued", "running") and uid not in _active:
        st = {**st, "state": "failed", "error": "interrupted (the app restarted); upload again"}
    return {**read_json(d / "meta.json"), "status": st}


def list_uploads() -> list:
    if not UPLOADS.exists():
        return []
    out = []
    for d in UPLOADS.iterdir():
        try:
            out.append(info(d.name))
        except KeyError:
            continue
    return sorted(out, key=lambda u: u["created_utc"], reverse=True)


def create(after: Path, meta: dict, before: Path | None = None) -> str:
    """Register an upload whose files are already saved in folder(uid) and queue it."""
    uid = after.parent.name
    meta = {**meta, "id": uid, "after_file": after.name, "before_file": before.name if before else None,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    (after.parent / "meta.json").write_text(json.dumps(meta))
    set_status(uid, state="queued", step="Waiting for the previous job")
    _active.add(uid)
    _queue.put(uid)
    _ensure_worker()
    return uid


def new_folder() -> tuple[str, Path]:
    uid = "upl_" + uuid.uuid4().hex[:8]
    d = folder(uid)
    d.mkdir(parents=True)
    return uid, d


def _ensure_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, name="uploads", daemon=True)
        _worker.start()


def _work():
    while True:
        uid = _queue.get()
        try:
            set_status(uid, state="running")
            rec = process(uid)
            set_status(uid, state="done", step="Done", assessment_id=rec["id"], alerts=len(rec["alerts"]))
        except Exception as e:  # noqa: BLE001  report any failure on the upload rather than killing the worker
            set_status(uid, state="failed", error=str(e) if isinstance(e, imagery.ImageryError) else f"{type(e).__name__}: {e}",
                       trace=traceback.format_exc()[-2000:])
        finally:
            _active.discard(uid)


# ---- pipeline -----------------------------------------------------------------------------------------------

def resample(g: imagery.GeoImage, metres: float) -> imagery.GeoImage:
    s = imagery.pixel_size_m(g) / metres
    h, w = g.shape
    nh, nw = max(1, round(h * s)), max(1, round(w * s))
    rgb = cv2.resize(g.rgb, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return imagery.GeoImage(rgb, g.crs, g.transform * Affine.scale(w / nw, h / nh))


def find_before(after: imagery.GeoImage, event_date: str | None):
    """Mosaic archive before-images onto the after grid, largest overlap first."""
    arch = xbd_archive()
    pre = np.zeros_like(after.rgb)
    valid = np.zeros(after.shape, bool)
    used = []
    for c in arch.search(imagery.footprint_lonlat(after), before=event_date, limit=8):
        rgb, tf, crs = arch.load(c)
        p, v = imagery.reproject_into(rgb, tf, crs, after)
        new = v & ~valid
        if new.mean() < 0.01:
            continue
        pre[new] = p[new]
        valid |= new
        used.append({"tile": c["tile"], "capture_date": c["capture_date"], "covers": round(float(new.mean()), 4)})
        if valid.mean() > 0.995:
            break
    return pre, valid, {"kind": "archive", "archive": arch.name, "tiles": used}


def process(uid: str) -> dict:
    d = folder(uid)
    meta = read_json(d / "meta.json")
    notes = []

    set_status(uid, step="Reading after image")
    after = imagery.read_image(d / meta["after_file"], meta.get("after_bounds"))
    px = imagery.pixel_size_m(after)
    if not KEEP_M[0] <= px <= KEEP_M[1]:
        after = resample(after, TARGET_M)
        notes.append(f"After image resampled from {px:.2f} m to {TARGET_M} m per pixel to match the training imagery.")
    if px > COARSE_M:
        notes.append(f"After image is coarser ({px:.1f} m per pixel) than the training imagery; damage classes are less reliable.")
    if max(after.shape) > MAX_SIDE:
        raise imagery.ImageryError(f"image covers {after.shape[1]} x {after.shape[0]} px at {imagery.pixel_size_m(after):.2f} m; "
                                   f"crop it to at most {MAX_SIDE} px per side (about {MAX_SIDE * TARGET_M / 1000:.0f} km)")
    post = after.rgb
    post_valid = post.max(-1) > 0

    set_status(uid, step="Finding the before image")
    if meta.get("before_file"):
        b = imagery.read_image(d / meta["before_file"], meta.get("before_bounds") or meta.get("after_bounds"))
        pre, valid = imagery.reproject_into(b.rgb, b.transform, b.crs, after)
        source = {"kind": "upload", "file": meta["before_file"]}
    else:
        pre, valid, source = find_before(after, meta.get("event_date"))
    valid &= post_valid

    set_status(uid, step="Aligning before and after")
    qa = {"coverage": float(valid.sum() / max(post_valid.sum(), 1)), "shift_px": None, "shift_m": None,
          "response": None, "corrected": False}
    if qa["coverage"] > 0.25:
        est = imagery.estimate_shift(pre, post, valid)
        if est and est[2] < MIN_RESPONSE:
            qa["response"] = round(est[2], 3)
            notes.append("The before and after images differ too much to measure an offset; their georeferencing is used as given.")
        elif est:
            dx, dy, resp = est
            mag = math.hypot(dx, dy)
            qa.update(shift_px=[round(dx, 2), round(dy, 2)], shift_m=round(mag * imagery.pixel_size_m(after), 2),
                      response=round(resp, 3))
            if SHIFT_MIN_PX <= mag <= SHIFT_MAX_PX:
                pre, valid = imagery.shift_image(pre, valid, dx, dy)
                valid &= post_valid
                qa["corrected"] = True
                qa["coverage"] = float(valid.sum() / max(post_valid.sum(), 1))
            elif mag > SHIFT_MAX_PX:
                notes.append(f"Before and after images appear offset by {qa['shift_m']} m; the offset was not corrected, "
                             "check the georeferencing.")
    pre[~valid] = 0
    cv2.imwrite(str(d / "post.jpg"), cv2.cvtColor(post, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(d / "pre.jpg"), cv2.cvtColor(pre, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])

    set_status(uid, step="Detecting buildings and damage")
    model_id = meta["model_id"]
    models = service.models()
    eng = service.engine(model_id)
    post_id = "unet_post" if "unet_post" in models else None
    if eng.uses_pre and qa["coverage"] > 0:
        loc_p, dmg_p = eng.predict_large(pre, post)
        if qa["coverage"] < 0.999:
            if not post_id:
                raise imagery.ImageryError("the before image does not cover the whole area and no post-only model is available")
            lp, dp = service.engine(post_id).predict_large(post, post)
            loc_p = np.where(valid, loc_p, lp)
            dmg_p[:, ~valid] = dp[:, ~valid]
            mode = f"before + after on {qa['coverage']:.1%} of the area, after only elsewhere"
        else:
            mode = eng.mode
    else:
        if eng.uses_pre:
            if not post_id:
                raise imagery.ImageryError("no before image covers this area and no post-only model is available")
            notes.append("No before image covers this area; the after image was assessed on its own.")
            eng = service.engine(post_id)
        loc_p, dmg_p = eng.predict_large(post, post)
        mode = eng.mode
    loc = (loc_p > 0.5) & post_valid
    dmg = (dmg_p.argmax(0) + 1).astype(np.uint8) * loc

    set_status(uid, step="Raising area alerts")
    to_lonlat = imagery.to_lonlat_fn(after)
    h, w = after.shape
    lon, lat = to_lonlat(w / 2, h / 2)
    dates = sorted({t["capture_date"] for t in source.get("tiles", []) if t["capture_date"]})
    scene_info = {"pair_id": uid, "source": "upload", "split": "upload", "name": meta["name"],
                  "disaster": meta["name"], "disaster_type": meta["disaster_type"],
                  "event_date": meta.get("event_date"), "centre_lat": lat, "centre_lon": lon,
                  "pixel_size_m": imagery.pixel_size_m(after), "size_px": max(h, w), "width_px": w, "height_px": h,
                  "geotransform": imagery.approx_geotransform(after),
                  "pre_date": ", ".join(dates) if dates else ("uploaded" if source["kind"] == "upload" else "none found"),
                  "post_date": meta.get("event_date") or "not given",
                  "before": {**source, **qa}, "notes": notes}
    return service.area_record(uid, scene_info, eng_id(eng, model_id, post_id), eng, loc, dmg, dmg_p, to_lonlat,
                               scene_info["pixel_size_m"], extra={"inference_mode": mode})


def eng_id(eng, model_id, post_id):
    """Model the record is filed under: the requested one, or the post-only fallback when no before image was found."""
    return model_id if eng is service.engine(model_id) else post_id
