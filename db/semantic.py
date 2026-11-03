"""The semantic layer: the governed definitions the application reads instead of constants buried in code.

  damage classes   code, label, colour, definition, whether it counts as severe
  metrics          versioned definitions (xView2 score, severe share, priority ...) with their formula and source
  glossary         what the entities and rules mean (alert, structure, four-eyes rule ...)
  model versions   every trained network with its checkpoint hash and scores; exactly one is the approved default
  thresholds       values that change behaviour (review confidence), each with who set it and when

Everything lives in schema `sem`; reference data is created by migration 0002 and the model rows by `sync_models`.
"""
import hashlib
import json
import threading
import time
from pathlib import Path

from .engine import one, rows, run, tx

_hash_cache: dict = {}
_threshold_cache: dict = {}
_lock = threading.Lock()
THRESHOLD_TTL = 30.0
DEFAULTS = {"review_confidence": 0.7}   # only used by tests that run without the seed; the database value is the source of truth


def file_sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _lock:
        if key not in _hash_cache:
            h = hashlib.sha256()
            with path.open("rb") as f:
                for blk in iter(lambda: f.read(1 << 20), b""):
                    h.update(blk)
            _hash_cache[key] = h.hexdigest()
        return _hash_cache[key]


# ---- reference data -------------------------------------------------------------------------------------------

def classes() -> list:
    with tx() as c:
        return rows(c, "SELECT code, key, label, colour, severe, definition FROM sem.damage_classes ORDER BY code")


def metrics(active_only: bool = True) -> list:
    with tx() as c:
        return rows(c, "SELECT key, version, name, description, formula, unit, status, owner, effective_from::text AS effective_from, source_ref FROM sem.metrics "
                       + ("WHERE status = 'active' " if active_only else "") + "ORDER BY key, version")


def glossary() -> list:
    with tx() as c:
        return rows(c, "SELECT term, kind, definition, see_also, source_ref FROM sem.glossary ORDER BY term")


def metric_versions() -> dict:
    """The version of each active metric definition: stored with an assessment so a number can be traced to the definition it used."""
    with tx() as c:
        return {r["key"]: r["version"] for r in rows(c, "SELECT key, version FROM sem.metrics WHERE status = 'active'")}


# ---- thresholds -----------------------------------------------------------------------------------------------

def threshold(key: str) -> float:
    now = time.monotonic()
    hit = _threshold_cache.get(key)
    if hit and now - hit[0] < THRESHOLD_TTL:
        return hit[1]
    with tx() as c:
        r = one(c, "SELECT value FROM sem.thresholds WHERE key = :k AND effective_from <= now() ORDER BY effective_from DESC, id DESC LIMIT 1", k=key)
    val = float(r["value"]) if r else DEFAULTS[key]
    _threshold_cache[key] = (now, val)
    return val


def thresholds() -> list:
    with tx() as c:
        return rows(c, "SELECT DISTINCT ON (key) key, value::float AS value, to_char(effective_from AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS effective_utc, "
                       "set_by, decision_ref, note FROM sem.thresholds WHERE effective_from <= now() ORDER BY key, effective_from DESC, id DESC")


def threshold_history(key: str) -> list:
    with tx() as c:
        return rows(c, "SELECT value::float AS value, to_char(effective_from AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS effective_utc, set_by, decision_ref, note "
                       "FROM sem.thresholds WHERE key = :k ORDER BY effective_from DESC, id DESC", k=key)


def set_threshold(key: str, value: float, by: str, decision_ref: str, note: str = "") -> None:
    if key not in DEFAULTS:
        raise ValueError(f"unknown threshold {key}")
    if not 0 < value < 1:
        raise ValueError("the review confidence must be between 0 and 1")
    with tx() as c:
        run(c, "INSERT INTO sem.thresholds (key, value, set_by, decision_ref, note) VALUES (:k, :v, :b, :d, :n)", k=key, v=value, b=by, d=decision_ref, n=note)
    _threshold_cache.pop(key, None)


# ---- model versions -------------------------------------------------------------------------------------------

def sync_models(models: dict, approved_seed: Path | None = None) -> None:
    """Make sure every model the server can load has a row, with its checkpoint hash and scores. When no model is approved yet, the one named in
    `approved_seed` (the file the approval was kept in before the database) becomes the approved default, once."""
    with tx() as c:
        run(c, "SELECT pg_advisory_xact_lock(727003)")
        for mid, m in models.items():
            ck = Path(m["run_dir"]) / "best.pt" if m.get("run_dir") else None
            sha = file_sha256(ck) if ck is not None and ck.exists() else None
            metrics = {"test_score": m.get("test_score")} if m.get("test_score") is not None else {}
            run(c, "INSERT INTO sem.model_versions (id, label, kind, run_name, checkpoint_sha256, metrics) VALUES (:i, :l, :k, :r, :s, CAST(:m AS jsonb)) "
                   "ON CONFLICT (id) DO UPDATE SET label = :l, kind = :k, run_name = :r, checkpoint_sha256 = :s, "
                   "metrics = sem.model_versions.metrics || CAST(:m AS jsonb)",
                i=mid, l=m.get("label", mid), k=m["kind"], r=Path(m["run_dir"]).name if m.get("run_dir") else None, s=sha, m=json.dumps(metrics))
        if approved_seed and approved_seed.exists() and not one(c, "SELECT 1 AS x FROM sem.model_versions WHERE status = 'approved'"):
            try:
                seed = json.loads(approved_seed.read_text())
            except ValueError:
                seed = {}
            if seed.get("default_model") in models:
                run(c, "UPDATE sem.model_versions SET status = 'approved', approved_by = :b, approved_at = COALESCE(CAST(:d AS timestamptz), now()), "
                       "approval_reason = :r, previous_model = :p, decision_ref = 'governance/decision_log.md' WHERE id = :i",
                    i=seed["default_model"], b=(seed.get("approved_by") or "imported").split(" (")[0], d=seed.get("approved_utc"),
                    r=seed.get("reason"), p=seed.get("previous"))


def approved_model() -> dict:
    with tx() as c:
        r = one(c, "SELECT id, approved_by, to_char(approved_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS approved_utc, approval_reason AS reason, previous_model AS previous, "
                   "checkpoint_sha256 FROM sem.model_versions WHERE status = 'approved'")
    return {"default_model": r["id"], "approved_utc": r["approved_utc"], "approved_by": r["approved_by"], "reason": r["reason"], "previous": r["previous"],
            "checkpoint_sha256": r["checkpoint_sha256"]} if r else {"default_model": None}


def approved_id() -> str | None:
    return approved_model().get("default_model")


def approve_model(model_id: str, by: str, reason: str, decision_ref: str = "governance/decision_log.md") -> dict:
    with tx() as c:
        run(c, "SELECT pg_advisory_xact_lock(727003)")
        if not one(c, "SELECT 1 AS x FROM sem.model_versions WHERE id = :i", i=model_id):
            raise KeyError(model_id)
        old = one(c, "SELECT id FROM sem.model_versions WHERE status = 'approved'")
        run(c, "UPDATE sem.model_versions SET status = 'candidate' WHERE status = 'approved'")
        run(c, "UPDATE sem.model_versions SET status = 'approved', approved_by = :b, approved_at = now(), approval_reason = :r, previous_model = :p, decision_ref = :d WHERE id = :i",
            i=model_id, b=by, r=reason, p=old["id"] if old else None, d=decision_ref)
    return approved_model()


def model_versions() -> list:
    with tx() as c:
        return rows(c, "SELECT id, label, kind, run_name, checkpoint_sha256, metrics, status, approved_by, approval_reason, "
                       "to_char(approved_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS approved_utc FROM sem.model_versions ORDER BY status = 'approved' DESC, id")
