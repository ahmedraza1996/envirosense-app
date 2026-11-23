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

from .engine import one, rows, run, tx, using

_hash_cache: dict = {}
_threshold_cache: dict = {}
_lock = threading.Lock()
THRESHOLD_TTL = 30.0
# value used only when the database has no row yet (tests that run without the seed); the database value is the source of truth.
# Each threshold: (default, lowest allowed, highest allowed, what it is)
LIMITS = {
    "review_confidence": (0.7, 0.01, 0.99, "Structures below this confidence are marked for review"),
    "alert_min_severe_m2": (250.0, 25.0, 5000.0, "Severely damaged roof area (m²) that raises an area alert"),
    "alert_eps_m": (30.0, 5.0, 200.0, "Damage within this distance (m) belongs to one area"),
    "alert_majority": (0.5, 0.1, 0.95, "High severity when at least this share of the building area is severely damaged"),
    "abstain_low_conf_share": (0.6, 0.1, 1.0, "The image is not assessed when more than this share of the structures is unsure"),
    "unusual_max_outside": (2.0, 0.0, 10.0, "An image is unusual when more image statistics than this are outside the training range"),
    "blank_max_share": (0.4, 0.05, 0.95, "The image is not assessed when more than this share is blank or cloud"),
    "live_precision_floor": (0.6, 0.1, 0.99, "Incident when fewer than this share of recent reviewed alerts were confirmed"),
    "live_precision_window": (30.0, 5.0, 500.0, "Number of recent decided alerts the live precision uses"),
    "drift_ratio": (2.0, 1.1, 10.0, "Incident when the share of unusual uploads grows by this factor"),
    "rubber_stamp_seconds": (5.0, 1.0, 60.0, "A confirmation faster than this (s) counts as a possible rubber stamp"),
}
DEFAULTS = {k: v[0] for k, v in LIMITS.items()}


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
        rs = rows(c, "SELECT DISTINCT ON (key) id AS version, key, value::float AS value, to_char(effective_from AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS effective_utc, "
                     "set_by, decision_ref, note FROM sem.thresholds WHERE effective_from <= now() ORDER BY key, effective_from DESC, id DESC")
    for r in rs:
        lim = LIMITS.get(r["key"])
        r.update(min=lim[1], max=lim[2], description=lim[3]) if lim else None
    return rs


def threshold_versions(keys) -> dict:
    """{key: row id} of the values in force: stored with a result, so the exact rule that produced it can be looked up."""
    with tx() as c:
        return {r["key"]: r["id"] for r in rows(c, "SELECT DISTINCT ON (key) key, id FROM sem.thresholds WHERE key = ANY(:k) AND effective_from <= now() "
                                                   "ORDER BY key, effective_from DESC, id DESC", k=list(keys))}


def threshold_history(key: str) -> list:
    with tx() as c:
        return rows(c, "SELECT value::float AS value, to_char(effective_from AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS effective_utc, set_by, decision_ref, note "
                       "FROM sem.thresholds WHERE key = :k ORDER BY effective_from DESC, id DESC", k=key)


def set_threshold(key: str, value: float, by: str, decision_ref: str, note: str = "", c=None) -> None:
    if key not in LIMITS:
        raise ValueError(f"unknown threshold {key}")
    _, lo, hi, what = LIMITS[key]
    if not lo <= value <= hi:
        raise ValueError(f"{what.lower()}: the value must be between {lo:g} and {hi:g}")
    with using(c) as conn:
        run(conn, "INSERT INTO sem.thresholds (key, value, set_by, decision_ref, note) VALUES (:k, :v, :b, :d, :n)", k=key, v=value, b=by, d=decision_ref, n=note)
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


def approve_model(model_id: str, by: str, reason: str, decision_ref: str = "governance/decision_log.md", c=None) -> dict | None:
    """Make a model version the approved default. With `c` the change joins the caller's transaction (and nothing is returned until it commits)."""
    with using(c) as conn:
        run(conn, "SELECT pg_advisory_xact_lock(727003)")
        if not one(conn, "SELECT 1 AS x FROM sem.model_versions WHERE id = :i", i=model_id):
            raise KeyError(model_id)
        old = one(conn, "SELECT id FROM sem.model_versions WHERE status = 'approved'")
        run(conn, "UPDATE sem.model_versions SET status = 'candidate' WHERE status = 'approved'")
        run(conn, "UPDATE sem.model_versions SET status = 'approved', approved_by = :b, approved_at = now(), approval_reason = :r, previous_model = :p, decision_ref = :d WHERE id = :i",
            i=model_id, b=by, r=reason, p=old["id"] if old else None, d=decision_ref)
    return approved_model() if c is None else None


def model_versions() -> list:
    with tx() as c:
        return rows(c, "SELECT id, label, kind, run_name, checkpoint_sha256, metrics, status, approved_by, approval_reason, "
                       "to_char(approved_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS approved_utc FROM sem.model_versions ORDER BY status = 'approved' DESC, id")
