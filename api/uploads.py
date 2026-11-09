"""Uploaded imagery -> area alerts.

One job at a time per server process, on CPU, claimed from the ingest.jobs table by a background thread (a job survives a restart):
  1 read the after image (GeoTIFF, or PNG/JPEG with corner coordinates); resample to the training resolution if needed
  2 before image: the user's own, or found in the archive by location (captured before the event date when one is
    given); archive tiles are mosaicked onto the after image's pixel grid
  3 alignment check: phase correlation measures any remaining shift; small shifts are corrected; coverage is recorded
  4 the U-Net locates buildings and classifies damage: before + after wherever a before image covers the ground,
    after only elsewhere (the post-only model), so a partial before image never blocks the assessment
  5 structures and area alerts, exactly as for benchmark tiles
The upload's details, its jobs and their steps are rows in schema ingest; its files live in runs/app/uploads/<id>/ (inputs, aligned
before/after JPEGs); the assessment record goes to the shared assessment store, so maps, crops and reports work unchanged.
"""
import json
import math
import os
import re
import socket
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from rasterio.transform import Affine

from ..db.engine import one, rows, run, tx
from . import geoimage, imagery, registration, service
from .archive import xbd_archive
from .engines import ROOT

UPLOADS = ROOT / "runs" / "app" / "uploads"
EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg")
MAX_BYTES = 300 * 2 ** 20
MAX_SIDE = 8192              # px after resampling (about 4 km at 0.5 m): bounds CPU time and memory; larger images are processed in blocks
BLOCKS_ABOVE = 2048          # images with a side above this are processed block by block (streaming)
TARGET_M = 0.5               # metres per pixel used when an image is far from the training resolution
KEEP_M = (0.25, 0.9)         # xBD tiles are roughly 0.3-0.6 m per pixel; inside this range the image is used as is
COARSE_M = 1.2               # beyond this, damage classes are unreliable (noted on the record)
SHIFT_MIN_PX, SHIFT_MAX_PX, MIN_RESPONSE = 1.5, 48, 0.05   # response: phase-correlation peak
ROT_MIN_DEG, SCALE_MIN = 0.15, 0.002                        # smaller rotation / zoom than this is left alone
DISASTER_TYPES = ("earthquake", "fire", "flooding", "wind", "tsunami", "volcano", "other")

_worker = None
_worker_lock = threading.Lock()
_local = threading.local()                  # the job this thread is running
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
HEARTBEAT_S, STALE_S, POLL_S = 20, 120, 2
_STATE = {"queued": "queued", "running": "running", "succeeded": "done", "failed": "failed", "cancelled": "failed"}
_STAMP = "YYYY-MM-DD HH24:MI:SS"


def is_upload(key: str) -> bool:
    return key.startswith("upl_")


def folder(uid: str) -> Path:
    if not re.fullmatch(r"upl_[0-9a-f]{8}", uid):
        raise KeyError(uid)
    return UPLOADS / uid


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


# ---- records in the database ----------------------------------------------------------------------------------

_SELECT = (f"SELECT u.id, u.unit_id, u.created_by, u.name, u.disaster_type, to_char(u.event_date, 'YYYY-MM-DD') AS event_date, u.model_id, u.after_file, "
           f"u.before_file, u.after_bounds, u.before_bounds, u.meta, to_char(u.created_at AT TIME ZONE 'UTC', '{_STAMP}') AS created_utc, "
           f"j.id AS job_id, j.state, j.step, j.error, j.error_detail, j.result, j.attempts, "
           f"to_char(COALESCE(j.finished_at, j.heartbeat_at, j.created_at) AT TIME ZONE 'UTC', '{_STAMP}') AS updated_utc "
           f"FROM ingest.uploads u LEFT JOIN LATERAL (SELECT * FROM ingest.jobs WHERE upload_id = u.id ORDER BY id DESC LIMIT 1) j ON true")


def _shape(r: dict) -> dict:
    """The upload as the interface knows it: its details and a `status` block."""
    st = {"state": _STATE.get(r["state"], "failed"), "step": r["step"] or "", "attempts": r["attempts"], "updated_utc": r["updated_utc"], **(r["result"] or {})}
    if st["state"] == "done" and st.get("stage") == "alignment":
        st["state"], st["step"] = "review", "Check the alignment"
    if r["error"]:
        st.update(error=r["error"], trace=r["error_detail"])
    meta = {k: v for k, v in (r["meta"] or {}).items()}
    return {**meta, "id": r["id"], "name": r["name"], "disaster_type": r["disaster_type"], "event_date": r["event_date"], "model_id": r["model_id"],
            "after_bounds": r["after_bounds"], "before_bounds": r["before_bounds"], "after_file": r["after_file"], "before_file": r["before_file"],
            "created_utc": r["created_utc"], "created_by": r["created_by"], "unit": r["unit_id"], "status": st}


def get_meta(uid: str) -> dict:
    return {k: v for k, v in info(uid).items() if k != "status"}


def info(uid: str) -> dict:
    folder(uid)                                   # rejects ids that are not upload ids
    with tx() as c:
        r = one(c, _SELECT + " WHERE u.id = :i", i=uid)
    if not r:
        raise KeyError(uid)
    return _shape(r)


def list_uploads(units: set | None = None) -> list:
    with tx() as c:
        rs = rows(c, _SELECT + (" WHERE u.unit_id = ANY(:u)" if units is not None else "") + " ORDER BY u.created_at DESC", **({"u": sorted(units)} if units is not None else {}))
    return [_shape(r) for r in rs]


RETENTION = Path(__file__).resolve().parents[1] / "governance" / "retention.json"


def policy() -> dict:
    """Retention rule and upload notice (governance/retention.json). No days set: uploads are kept until the user deletes them."""
    try:
        return json.loads(RETENTION.read_text())
    except (OSError, ValueError):
        return {"upload_retention_days": None, "notice": "Uploads are kept until you delete them."}


def expired(days: int | None, now: datetime | None = None) -> list:
    if not days:
        return []
    with tx() as c:
        return [r["id"] for r in rows(c, "SELECT u.id FROM ingest.uploads u WHERE u.created_at <= COALESCE(CAST(:n AS timestamptz), now()) - make_interval(days => :d) "
                                         "AND NOT EXISTS (SELECT 1 FROM ingest.jobs j WHERE j.upload_id = u.id AND j.state IN ('queued', 'running'))", d=days, n=now)]


def purge_expired() -> list:
    """Delete uploads past the retention period (when one is set); each deletion is written to the audit log."""
    from . import audit
    gone = []
    for uid in expired(policy().get("upload_retention_days")):
        try:
            delete(uid)
            audit.log("delete_upload", "system (retention rule)", uid, retention_days=policy().get("upload_retention_days"))
            gone.append(uid)
        except Exception:  # noqa: BLE001  a busy or half-removed upload is tried again at the next start
            continue
    return gone


def register(uid: str, meta: dict, unit: str, by: str, queue: bool = True) -> None:
    """Insert the upload's row (details, owner unit) and, unless `queue` is False, its job."""
    keep = {k: v for k, v in meta.items() if k not in ("id", "name", "disaster_type", "event_date", "model_id", "after_file", "before_file",
                                                          "after_bounds", "before_bounds", "created_utc")}
    with tx() as c:
        run(c, "INSERT INTO ingest.uploads (id, unit_id, created_by, name, disaster_type, event_date, model_id, after_file, before_file, after_bounds, before_bounds, meta, created_at) "
               "VALUES (:i, :u, :b, :n, :t, CAST(:d AS date), :m, :af, :bf, CAST(:ab AS jsonb), CAST(:bb AS jsonb), CAST(:meta AS jsonb), COALESCE(CAST(:at AS timestamptz), now()))",
            i=uid, u=unit, b=by, n=meta["name"], t=meta["disaster_type"], d=meta.get("event_date"), m=meta.get("model_id"), af=meta["after_file"], bf=meta.get("before_file"),
            ab=json.dumps(meta.get("after_bounds")), bb=json.dumps(meta.get("before_bounds")), meta=json.dumps(keep), at=meta.get("created_utc"))
        if queue:
            run(c, "INSERT INTO ingest.jobs (upload_id, step, created_by) VALUES (:i, 'Waiting for the previous job', :b)", i=uid, b=by)


def create(after: Path, meta: dict, before: Path | None = None) -> str:
    """Register an upload whose files are already saved in folder(uid) and queue its job. The upload belongs to the signed-in user's unit."""
    from . import auth
    user = auth.current()
    if user is None:
        raise PermissionError("an upload needs a signed-in user")
    uid = after.parent.name
    register(uid, {**meta, "after_file": after.name, "before_file": before.name if before else None}, user["unit"], user["username"])
    _ensure_worker()
    return uid


def delete(uid: str) -> None:
    """Remove an upload with everything derived from it: inputs, images, stored assessments, crops, caches, and (by cascade) its jobs,
    alerts and reviews."""
    import shutil
    d = folder(uid)
    with tx() as c:
        if not one(c, "SELECT 1 AS x FROM ingest.uploads WHERE id = :i FOR UPDATE", i=uid):
            raise KeyError(uid)
        if one(c, "SELECT 1 AS x FROM ingest.jobs WHERE upload_id = :i AND state IN ('queued', 'running')", i=uid):
            raise imagery.ImageryError("this upload is still being processed; wait for it to finish")
        run(c, "DELETE FROM ingest.uploads WHERE id = :i", i=uid)
    shutil.rmtree(d, ignore_errors=True)
    for root in (service.STORE, service.CACHE / "crops", service.CACHE / "geo", service.CACHE / "osm"):
        for f in root.glob(f"{uid}*"):
            f.unlink(missing_ok=True)


def update(uid: str, name: str | None = None, disaster_type: str | None = None, event_date: str | None = None) -> dict:
    """Rename an upload or correct its type / event date; the stored assessment carries the same details."""
    cur = info(uid)
    if name is not None:
        cur["name"] = name.strip()[:80] or cur["name"]
    if disaster_type is not None:
        if disaster_type not in DISASTER_TYPES:
            raise imagery.ImageryError(f"disaster_type must be one of {', '.join(DISASTER_TYPES)}")
        cur["disaster_type"] = disaster_type
    if event_date is not None:
        if event_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
            raise imagery.ImageryError("event_date must be YYYY-MM-DD")
        cur["event_date"] = event_date or None
    with tx() as c:
        run(c, "UPDATE ingest.uploads SET name = :n, disaster_type = :t, event_date = CAST(:d AS date) WHERE id = :i", n=cur["name"], t=cur["disaster_type"], d=cur["event_date"], i=uid)
    for f in service.STORE.glob(f"{uid}__*__area.json"):
        rec = json.loads(f.read_text())
        rec["scene"].update(name=cur["name"], disaster=cur["name"], disaster_type=cur["disaster_type"],
                            event_date=cur["event_date"], post_date=cur["event_date"] or "not given")
        f.write_text(json.dumps(rec))
    return info(uid)


def new_folder() -> tuple[str, Path]:
    uid = "upl_" + uuid.uuid4().hex[:8]
    d = folder(uid)
    d.mkdir(parents=True)
    return uid, d


# ---- the job queue --------------------------------------------------------------------------------------------

def set_status(uid: str, step: str | None = None, **_ignored):
    """Record the step the running job has reached (a row in ingest.job_steps) and show a sign of life (the heartbeat)."""
    job = getattr(_local, "job", None)
    if job is None or step is None:
        return
    with tx() as c:
        run(c, "UPDATE ingest.job_steps SET state = 'ok', finished_at = now() WHERE job_id = :j AND state = 'running'", j=job)
        run(c, "INSERT INTO ingest.job_steps (job_id, seq, name, state) SELECT :j, COALESCE(MAX(seq), 0) + 1, :n, 'running' FROM ingest.job_steps WHERE job_id = :j", j=job, n=step)
        run(c, "UPDATE ingest.jobs SET step = :n, heartbeat_at = now() WHERE id = :j", j=job, n=step)


def requeue_stale() -> int:
    """A running job whose heartbeat stopped (the worker died or the server restarted) goes back to the queue; after max_attempts it fails."""
    with tx() as c:
        run(c, "UPDATE ingest.job_steps s SET state = 'failed', finished_at = now() FROM ingest.jobs j WHERE s.job_id = j.id AND s.state = 'running' "
               "AND j.state = 'running' AND j.heartbeat_at < now() - make_interval(secs => :s)", s=STALE_S)
        a = run(c, "UPDATE ingest.jobs SET state = 'queued', locked_by = NULL, step = 'Waiting for the previous job' WHERE state = 'running' AND attempts < max_attempts "
                   "AND heartbeat_at < now() - make_interval(secs => :s)", s=STALE_S).rowcount
        b = run(c, "UPDATE ingest.jobs SET state = 'failed', finished_at = now(), error = 'the worker stopped and the job ran out of attempts; upload again' "
                   "WHERE state = 'running' AND attempts >= max_attempts AND heartbeat_at < now() - make_interval(secs => :s)", s=STALE_S).rowcount
    return a + b


def claim() -> tuple[int, str] | None:
    with tx() as c:
        r = one(c, "WITH nxt AS (SELECT id FROM ingest.jobs WHERE state = 'queued' AND run_after <= now() ORDER BY priority DESC, run_after, id "
                   "FOR UPDATE SKIP LOCKED LIMIT 1) "
                   "UPDATE ingest.jobs j SET state = 'running', locked_by = :w, heartbeat_at = now(), started_at = COALESCE(j.started_at, now()), attempts = j.attempts + 1 "
                   "FROM nxt WHERE j.id = nxt.id RETURNING j.id, j.upload_id", w=WORKER_ID)
    return (r["id"], r["upload_id"]) if r else None


def _finish(job: int, ok: bool, result: dict | None = None, error: str | None = None, detail: str | None = None) -> None:
    with tx() as c:
        run(c, "UPDATE ingest.job_steps SET state = :s, finished_at = now() WHERE job_id = :j AND state = 'running'", j=job, s="ok" if ok else "failed")
        run(c, "UPDATE ingest.jobs SET state = :st, finished_at = now(), step = CASE WHEN :ok THEN 'Done' ELSE step END, error = :e, error_detail = :d, "
               "result = CAST(:r AS jsonb) WHERE id = :j", j=job, st="succeeded" if ok else "failed", ok=ok, e=error, d=detail, r=json.dumps(result or {}))


def _beat(job: int, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_S):
        try:
            with tx() as c:
                run(c, "UPDATE ingest.jobs SET heartbeat_at = now() WHERE id = :j AND state = 'running'", j=job)
        except Exception:  # noqa: BLE001  a missed beat is retried at the next interval
            pass


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="uploads", daemon=True)
            _worker.start()


def _work():
    while True:
        try:
            requeue_stale()
            got = claim()
        except Exception:  # noqa: BLE001  the database is briefly unavailable: try again
            time.sleep(POLL_S * 5)
            continue
        if got is None:
            time.sleep(POLL_S)
            continue
        job, uid = got
        _local.job = job
        stop = threading.Event()
        threading.Thread(target=_beat, args=(job, stop), daemon=True).start()
        try:
            rec = process(uid)
            if rec is None:
                _finish(job, True, {"stage": "alignment", "needs_review": True})
            else:
                _finish(job, True, {"assessment_id": rec["id"], "alerts": len(rec["alerts"])})
        except Exception as e:  # noqa: BLE001  report any failure on the job rather than killing the worker
            _finish(job, False, error=str(e) if isinstance(e, imagery.ImageryError) else f"{type(e).__name__}: {e}", detail=traceback.format_exc()[-2000:])
        finally:
            stop.set()
            _local.job = None


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


ALIGN_FILE = "alignment.json"
PREVIEW_SIDE = 1600          # long side of the preview images shown in the alignment check
COLOUR_DIFF_WARN = 12.0      # mean CIELAB distance between the two images' colours above which the pair is flagged
CHOICES = ("auto", "manual", "placed", "after_only")


def _save_rgb(path: Path, rgb: np.ndarray) -> None:
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])


def _load_rgb(path: Path) -> np.ndarray:
    return cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def _save_mask(path: Path, m: np.ndarray) -> None:
    cv2.imwrite(str(path), m.astype(np.uint8) * 255, [cv2.IMWRITE_PNG_COMPRESSION, 1])


def _load_mask(path: Path) -> np.ndarray:
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED) > 0


def _preview(d: Path, name: str, rgb: np.ndarray, valid: np.ndarray | None = None) -> float:
    """A reduced JPEG for the alignment check; ground the image does not cover is grey. Returns the scale (preview px / full px)."""
    h, w = rgb.shape[:2]
    k = min(1.0, PREVIEW_SIDE / max(h, w))
    img = rgb if valid is None else np.where(valid[..., None], rgb, np.uint8(128))
    small = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else img
    cv2.imwrite(str(d / f"preview_{name}.jpg"), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 86])
    return k


def read_alignment(uid: str) -> dict | None:
    return read_json(folder(uid) / ALIGN_FILE)


def _write_alignment(uid: str, al: dict) -> dict:
    (folder(uid) / ALIGN_FILE).write_text(json.dumps(al, indent=1))
    return al


def _read_after(d: Path, meta: dict, notes: list) -> imagery.GeoImage:
    after = imagery.read_image(d / meta["after_file"], meta.get("after_bounds"))
    px = imagery.pixel_size_m(after)
    if not KEEP_M[0] <= px <= KEEP_M[1]:
        after = resample(after, TARGET_M)
        notes.append(f"After image resampled from {px:.2f} m to {TARGET_M} m per pixel to match the training imagery.")
    if px > COARSE_M:
        notes.append(f"After image is coarser ({px:.1f} m per pixel) than the training imagery; damage classes are less reliable.")
    if max(after.shape) > MAX_SIDE:
        raise imagery.ImageryError(f"image covers {after.shape[1]} x {after.shape[0]} px at {imagery.pixel_size_m(after):.2f} m; "
                                   f"crop it to at most {MAX_SIDE} px per side (about {MAX_SIDE * TARGET_M / 1000:.0f} km at {TARGET_M} m per pixel)")
    return after


def _auto_align(pre, valid, post, post_valid, pxm):
    """Learned registration, then phase correlation for what is left. Returns the aligned before image, its mask, the QA record and notes."""
    notes = []
    qa = {"coverage": float(valid.sum() / max(post_valid.sum(), 1)), "shift_px": None, "shift_m": None,
          "response": None, "corrected": False, "method": None, "rotation_deg": 0.0, "scale": 1.0,
          "matches": None, "inliers": None, "rms_px": None}
    if qa["coverage"] <= 0.25:
        return pre, valid, qa, notes
    total = np.zeros(2)                                  # translation of pre relative to post, pixels (shift convention)
    reg = registration.register(pre, post, valid)
    if reg.ok:
        qa.update(method=reg.method, matches=reg.matches, inliers=reg.inliers, rotation_deg=round(reg.rotation_deg, 3),
                  scale=round(reg.scale, 4), rms_px=round(reg.rms_px, 2))
        significant = abs(reg.rotation_deg) >= ROT_MIN_DEG or abs(reg.scale - 1) >= SCALE_MIN or reg.shift_px >= SHIFT_MIN_PX
        m = np.float32(reg.matrix)
        if significant and reg.shift_px <= SHIFT_MAX_PX * 4:
            h_, w_ = valid.shape
            v = m[:, :2] @ np.array([w_ / 2, h_ / 2]) + m[:, 2] - np.array([w_ / 2, h_ / 2])
            pre, valid = registration.apply(reg, pre, valid)
            valid &= post_valid
            total = -v
            qa["corrected"] = True
            bits = []
            if abs(reg.rotation_deg) >= ROT_MIN_DEG:
                bits.append(f"rotated by {reg.rotation_deg:+.2f} degrees")
            if abs(reg.scale - 1) >= SCALE_MIN:
                bits.append(f"zoom {100 * (reg.scale - 1):+.1f}%")
            if reg.shift_px >= SHIFT_MIN_PX:
                bits.append(f"shifted by {reg.shift_px * pxm:.1f} m")
            notes.append(f"The before image was registered to the after image from {reg.inliers} matching features "
                         f"({reg.method}): {', '.join(bits)}.")
    else:
        qa["method"] = "phase correlation"
        notes.append(f"Rotation and zoom could not be measured ({reg.reason}); only a shift was looked for.")
    est = imagery.estimate_shift(pre, post, valid)
    if est and est[2] < MIN_RESPONSE:
        qa["response"] = round(est[2], 3)
        if not qa["corrected"]:
            notes.append("The before and after images differ too much to measure an offset; their georeferencing is used as given.")
    elif est:
        dx, dy, resp = est
        mag = math.hypot(dx, dy)
        qa["response"] = round(resp, 3)
        if SHIFT_MIN_PX <= mag <= SHIFT_MAX_PX:
            pre, valid = imagery.shift_image(pre, valid, dx, dy)
            valid &= post_valid
            total = total + (dx, dy)
            qa["corrected"] = True
        elif mag > SHIFT_MAX_PX:
            notes.append(f"Before and after images appear offset by {mag * pxm:.1f} m; the offset was not corrected, check the georeferencing.")
    qa.update(shift_px=[round(float(total[0]), 2), round(float(total[1]), 2)], shift_m=round(float(np.hypot(*total)) * pxm, 2))
    qa["coverage"] = float(valid.sum() / max(post_valid.sum(), 1))
    return pre, valid, qa, notes


def _quality(qa: dict) -> dict:
    """Traffic light for the automatic alignment, with the reason in words."""
    if qa["coverage"] <= 0.25:
        return {"level": "none", "text": "No before image covers enough of the area to align."}
    learned = qa.get("method") not in (None, "phase correlation")
    if learned and (qa.get("inliers") or 0) >= 40 and (qa.get("rms_px") or 9) <= 2.5:
        return {"level": "good", "text": f"{qa['inliers']} matching features agree to {qa['rms_px']:.1f} px."}
    if learned or (qa.get("response") or 0) >= MIN_RESPONSE:
        why = f"only {qa['inliers']} matching features" if learned and (qa.get("inliers") or 0) < 40 else \
              (f"matching features disagree by {qa['rms_px']:.1f} px" if learned else "only a shift could be measured")
        return {"level": "check", "text": f"Aligned, but {why}: check the overlay."}
    return {"level": "poor", "text": "The images share too few features to align automatically; place tie points or use the coordinates only."}


def _colour_difference(pre, post, valid) -> float | None:
    if valid.sum() < 1000:
        return None
    idx = np.flatnonzero(valid.ravel())
    idx = idx[:: max(1, idx.size // 200_000)]
    lab = lambda a: cv2.cvtColor(a.reshape(-1, 1, 3)[idx], cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32) * [100 / 255, 1, 1] - [0, 128, 128]
    a, b = lab(pre), lab(post)
    return float(np.linalg.norm(a.mean(0) - b.mean(0)) + 0.5 * np.linalg.norm(a.std(0) - b.std(0)))


def _checks(meta, px_input, after, source, qa, pre, post, valid) -> list:
    """Input checks shown before the assessment runs: each {name, level ok|warn|fail, text}."""
    out = []
    add = lambda n, lv, t: out.append({"name": n, "level": lv, "text": t})
    add("Location", "ok", "Placed by its GeoTIFF georeference." if not meta.get("after_bounds") else "Placed by the corner coordinates given (north-up).")
    pxm = imagery.pixel_size_m(after)
    h, w = after.shape
    if KEEP_M[0] <= px_input <= KEEP_M[1]:
        add("Resolution", "ok", f"{px_input:.2f} m per pixel, as in the training imagery.")
    else:
        add("Resolution", "warn" if px_input <= COARSE_M else "fail",
            f"{px_input:.2f} m per pixel; resampled to {pxm:.2f} m." + ("" if px_input <= COARSE_M else " Damage classes are unreliable at this resolution."))
    add("Size", "ok", f"{w} x {h} px ({w * pxm / 1000:.1f} x {h * pxm / 1000:.1f} km)" + (", processed in blocks." if max(w, h) > BLOCKS_ABOVE else "."))
    if source["kind"] == "upload":
        add("Before image", "ok", "Uploaded with the after image.")
    elif source.get("tiles"):
        dates = sorted({t["capture_date"] for t in source["tiles"] if t.get("capture_date")})
        add("Before image", "ok", f"Found in the archive: {len(source['tiles'])} tile(s)" + (f", captured {', '.join(dates)}." if dates else "."))
        ev = meta.get("event_date")
        if ev and any(dt >= ev for dt in dates):
            add("Capture order", "fail", f"An archive image was captured on or after the event date ({ev}).")
        elif not ev:
            add("Capture order", "warn", "No event date given, so the archive could not be limited to images taken before the event.")
    else:
        add("Before image", "warn", "None found. Damage will be judged from the after image alone, which is less reliable.")
    cov = qa["coverage"]
    add("Overlap", "ok" if cov >= 0.9 else "warn" if cov > 0.25 else "fail",
        f"The before image covers {cov:.0%} of the after image." + ("" if cov >= 0.9 else " Elsewhere the after image is assessed on its own."))
    diff = _colour_difference(pre, post, valid)
    if diff is not None:
        add("Colour", "ok" if diff < COLOUR_DIFF_WARN else "warn",
            "Similar colour in both images." if diff < COLOUR_DIFF_WARN else
            "The two images differ strongly in colour (season, light or sensor); the model is less reliable on such pairs.")
    return out


def prepare(uid: str) -> dict:
    """Step 1 of an upload: read the images, place the before image on the after image's grid by its coordinates, align it automatically,
    run the input checks and write the previews. The assessment waits for a person to check the alignment unless the upload asked not to."""
    d = folder(uid)
    meta = get_meta(uid)
    notes = []
    set_status(uid, step="Reading after image")
    px_input = imagery.pixel_size_m(imagery.read_image(d / meta["after_file"], meta.get("after_bounds")))
    after = _read_after(d, meta, notes)
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
    _save_rgb(d / "post_full.png", post)
    _save_rgb(d / "before_placed.png", pre)
    _save_mask(d / "valid_placed.png", valid)

    set_status(uid, step="Aligning before and after")
    pxm = imagery.pixel_size_m(after)
    pre_a, valid_a, qa, auto_notes = _auto_align(pre.copy(), valid.copy(), post, post_valid, pxm)
    _save_rgb(d / "before_auto.png", pre_a)
    _save_mask(d / "valid_auto.png", valid_a)
    k = _preview(d, "after", post)
    _preview(d, "before_placed", pre, valid)
    _preview(d, "before_auto", pre_a, valid_a)
    has_before = qa["coverage"] > 0.25
    review = bool(meta.get("review_alignment")) and has_before
    h, w = post.shape[:2]
    al = {"state": "review" if review else "confirmed", "choice": "auto" if has_before else "after_only", "version": 1,
          "source": source, "auto": qa, "auto_notes": auto_notes, "quality": _quality(qa), "manual": None, "notes": notes,
          "checks": _checks(meta, px_input, after, source, qa, pre_a, post, valid_a), "pixel_size_m": pxm,
          "preview": {"scale": k, "width": round(w * k), "height": round(h * k)}, "confirmed_by": None if review else "automatic", "confirmed_utc": None}
    return _write_alignment(uid, al)


def _similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity (rotation, zoom, shift) mapping src points onto dst points; exact for two points."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    num = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum()
    den = (a * b).sum()
    theta = math.atan2(num, den)
    scale = math.hypot(num, den) / max((a ** 2).sum(), 1e-9)
    c, s = scale * math.cos(theta), scale * math.sin(theta)
    r = np.array([[c, -s], [s, c]])
    t = md - r @ ms
    return np.hstack([r, t[:, None]])


def manual_align(uid: str, pairs: list, by: str) -> dict:
    """Align the before image from tie points placed by a person. pairs: [[x_before, y_before, x_after, y_after], ...] in preview pixels."""
    al = read_alignment(uid)
    if not al or al["state"] != "review":
        raise imagery.ImageryError("the alignment of this upload is not open for checking")
    if len(pairs) < 2:
        raise imagery.ImageryError("place at least two pairs of matching points (three or more are better)")
    k = al["preview"]["scale"]
    pts = np.array(pairs, np.float64) / k
    m = _similarity(pts[:, :2], pts[:, 2:])
    d = folder(uid)
    post = _load_rgb(d / "post_full.png")
    pre, valid = _load_rgb(d / "before_placed.png"), _load_mask(d / "valid_placed.png")
    h, w = valid.shape
    pre_m = cv2.warpAffine(pre, np.float32(m), (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    valid_m = cv2.warpAffine(valid.astype(np.uint8), np.float32(m), (w, h), flags=cv2.INTER_NEAREST, borderValue=0).astype(bool) & (post.max(-1) > 0)
    _save_rgb(d / "before_manual.png", pre_m)
    _save_mask(d / "valid_manual.png", valid_m)
    _preview(d, "before_manual", pre_m, valid_m)
    pxm = al["pixel_size_m"]
    res = np.linalg.norm((pts[:, :2] @ m[:, :2].T + m[:, 2]) - pts[:, 2:], axis=1) * pxm
    centre = np.array([w / 2, h / 2])
    al["manual"] = {"pairs": pairs, "rotation_deg": round(math.degrees(math.atan2(m[1, 0], m[0, 0])), 3),
                    "scale": round(float(math.hypot(m[0, 0], m[1, 0])), 4),
                    "shift_m": round(float(np.linalg.norm(m[:, :2] @ centre + m[:, 2] - centre)) * pxm, 2),
                    "residuals_m": [round(float(r), 2) for r in res], "rms_m": round(float(np.sqrt((res ** 2).mean())), 2),
                    "coverage": float(valid_m.sum() / max((post.max(-1) > 0).sum(), 1)), "by": by,
                    "utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    al["choice"], al["version"] = "manual", al["version"] + 1
    return _write_alignment(uid, al)


def choose_alignment(uid: str, choice: str) -> dict:
    al = read_alignment(uid)
    if not al or al["state"] != "review":
        raise imagery.ImageryError("the alignment of this upload is not open for checking")
    if choice not in CHOICES or (choice == "manual" and not al.get("manual")):
        raise imagery.ImageryError("choose auto, placed, after_only, or manual after placing tie points")
    al["choice"], al["version"] = choice, al["version"] + 1
    return _write_alignment(uid, al)


def confirm_alignment(uid: str, by: str) -> dict:
    """A person accepted the alignment shown: record who and when, and queue the assessment."""
    al = read_alignment(uid)
    if not al or al["state"] != "review":
        raise imagery.ImageryError("the alignment of this upload is not open for checking")
    al.update(state="confirmed", confirmed_by=by, confirmed_utc=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    _write_alignment(uid, al)
    with tx() as c:
        run(c, "INSERT INTO ingest.jobs (upload_id, step, created_by) VALUES (:i, 'Waiting for the previous job', :b)", i=uid, b=by)
    _ensure_worker()
    return al


def process(uid: str) -> dict | None:
    """Run the next step of an upload. Returns None when the upload now waits for its alignment to be checked."""
    al = read_alignment(uid)
    if al is None:
        al = prepare(uid)
    if al["state"] == "review":
        return None
    return assess(uid, al)


def assess(uid: str, al: dict) -> dict:
    """Step 2: detect buildings and damage with the before image placed as chosen in the alignment check, and raise area alerts."""
    d = folder(uid)
    meta = get_meta(uid)
    after = _read_after(d, meta, [])
    notes = list(al["notes"])
    post = _load_rgb(d / "post_full.png")
    post_valid = post.max(-1) > 0
    source, choice = al["source"], al["choice"]
    files = {"auto": ("before_auto.png", "valid_auto.png"), "manual": ("before_manual.png", "valid_manual.png"),
             "placed": ("before_placed.png", "valid_placed.png")}
    if choice in files:
        pre, valid = _load_rgb(d / files[choice][0]), _load_mask(d / files[choice][1])
    else:
        pre, valid = np.zeros_like(post), np.zeros(post_valid.shape, bool)
    qa = dict(al["auto"])
    if choice == "auto":
        notes += al["auto_notes"]
    elif choice == "manual":
        mn = al["manual"]
        qa.update(method="manual tie points", corrected=True, rotation_deg=mn["rotation_deg"], scale=mn["scale"], shift_m=mn["shift_m"],
                  matches=len(mn["pairs"]), inliers=len(mn["pairs"]), rms_px=None)
        notes.append(f"The before image was aligned by hand from {len(mn['pairs'])} pairs of tie points (residual {mn['rms_m']:.1f} m).")
    elif choice == "placed":
        qa.update(method="coordinates only", corrected=False, rotation_deg=0.0, scale=1.0, shift_m=0.0, shift_px=[0.0, 0.0])
        notes.append("The before image is placed by its coordinates only; the automatic alignment was not used.")
    else:
        notes.append("The before image was not used; the after image was assessed on its own.")
    qa["coverage"] = float(valid.sum() / max(post_valid.sum(), 1))
    if al.get("confirmed_by") not in (None, "automatic"):
        notes.append(f"The alignment was checked by {al['confirmed_by']} ({al['confirmed_utc']} UTC) before the assessment ran.")
    qa["choice"] = choice
    pre = pre.copy()
    pre[~valid] = 0
    cv2.imwrite(str(d / "post.jpg"), cv2.cvtColor(post, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(d / "pre.jpg"), cv2.cvtColor(pre, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])

    set_status(uid, step="Detecting buildings and damage")
    model_id = meta["model_id"]
    models = service.models()
    eng = service.engine(model_id)
    post_id = "unet_post" if "unet_post" in models else None
    big = max(post.shape[:2]) > BLOCKS_ABOVE

    def progress(k, n):
        set_status(uid, step=f"Detecting buildings and damage (block {k} of {n})")

    def predict(engine, a_img, b_img, valid_=None, fallback=None):
        if big:
            return engine.predict_stream(a_img, b_img, valid_, fallback, progress=progress)
        return engine.predict_large(a_img, b_img)

    if eng.uses_pre and qa["coverage"] > 0:
        partial = qa["coverage"] < 0.999
        if partial and not post_id:
            raise imagery.ImageryError("the before image does not cover the whole area and no post-only model is available")
        if big:
            loc_p, dmg_p = predict(eng, pre, post, valid, service.engine(post_id) if partial else None)
        else:
            loc_p, dmg_p = eng.predict_large(pre, post)
            if partial:
                lp, dp = service.engine(post_id).predict_large(post, post)
                loc_p = np.where(valid, loc_p, lp)
                dmg_p[:, ~valid] = dp[:, ~valid]
        mode = f"before + after on {qa['coverage']:.1%} of the area, after only elsewhere" if partial else eng.mode
    else:
        if eng.uses_pre:
            if not post_id:
                raise imagery.ImageryError("no before image covers this area and no post-only model is available")
            notes.append("No before image covers this area; the after image was assessed on its own.")
            eng = service.engine(post_id)
        loc_p, dmg_p = predict(eng, post, post)
        mode = eng.mode
    if big:      # uint8 probabilities (x255)
        loc = (loc_p >= 128) & post_valid
    else:
        loc = (loc_p > 0.5) & post_valid
    dmg = (dmg_p.argmax(0) + 1).astype(np.uint8) * loc

    set_status(uid, step="Raising area alerts")
    to_lonlat = imagery.to_lonlat_fn(after)
    h, w = after.shape
    lon, lat = to_lonlat(w / 2, h / 2)
    dates = sorted({t["capture_date"] for t in source.get("tiles", []) if t["capture_date"]})
    gt = imagery.approx_geotransform(after)
    fit_err = imagery.geotransform_error_m(after)
    if fit_err > 0.5:
        notes.append(f"Outlines are placed with a linear fit of the image's projection; it can be off by up to {fit_err:.1f} m.")
    scene_info = {"pair_id": uid, "source": "upload", "split": "upload", "name": meta["name"],
                  "disaster": meta["name"], "disaster_type": meta["disaster_type"],
                  "event_date": meta.get("event_date"), "centre_lat": lat, "centre_lon": lon,
                  "pixel_size_m": imagery.pixel_size_m(after), "size_px": max(h, w), "width_px": w, "height_px": h,
                  "geotransform": gt, "geo_fit_error_m": round(fit_err, 3),
                  "geo_bounds": geoimage.bounds(gt, w, h, imagery.pixel_size_m(after)) if geoimage.is_rotated(gt) else None,
                  "pre_date": ", ".join(dates) if dates else ("uploaded" if source["kind"] == "upload" else "none found"),
                  "post_date": meta.get("event_date") or "not given",
                  "before": {**source, **qa}, "notes": notes}
    return service.area_record(uid, scene_info, eng_id(eng, model_id, post_id), eng, loc, dmg, dmg_p, to_lonlat,
                               scene_info["pixel_size_m"], extra={"inference_mode": mode})


def eng_id(eng, model_id, post_id):
    """Model the record is filed under: the requested one, or the post-only fallback when no before image was found."""
    return model_id if eng is service.engine(model_id) else post_id
