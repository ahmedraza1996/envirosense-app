"""Routes for the semantic layer (definitions, model versions, thresholds) and for the ingestion jobs."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import semantic
from ..db.engine import rows, tx
from . import audit, auth

router = APIRouter()


class ThresholdChange(BaseModel):
    value: float
    reason: str


@router.get("/api/semantic/classes")
def get_classes():
    return semantic.classes()


@router.get("/api/semantic/metrics")
def get_metrics(all_versions: bool = False):
    return semantic.metrics(active_only=not all_versions)


@router.get("/api/semantic/glossary")
def get_glossary():
    return semantic.glossary()


@router.get("/api/semantic/models")
def get_model_versions():
    return semantic.model_versions()


@router.get("/api/semantic/thresholds")
def get_thresholds():
    return semantic.thresholds()


@router.get("/api/semantic/thresholds/{key}/history")
def get_threshold_history(key: str):
    h = semantic.threshold_history(key)
    if not h:
        raise HTTPException(404, f"no threshold {key}")
    return h


@router.put("/api/admin/thresholds/{key}")
def put_threshold(key: str, body: ThresholdChange):
    """Change a threshold that alters what the application flags. Kept with who, when and why; recorded in the audit log."""
    if len(body.reason.strip()) < 10:
        raise HTTPException(400, "give the reason (at least 10 characters)")
    old = semantic.threshold(key) if key in semantic.DEFAULTS else None
    try:
        semantic.set_threshold(key, body.value, auth.actor(), "governance/decision_log.md", body.reason.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.log("threshold_change", auth.actor(), key=key, previous=old, value=body.value, reason=body.reason.strip())
    return semantic.thresholds()


@router.get("/api/jobs")
def get_jobs(limit: int = 50):
    """Ingestion jobs for uploads in the caller's unit tree, newest first, with their steps."""
    vis = sorted(auth.visible_units(auth.current()))
    with tx() as c:
        jobs = rows(c, "SELECT j.id, j.upload_id, u.name, j.state, j.step, j.attempts, j.max_attempts, j.error, "
                       "to_char(j.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS created_utc, "
                       "to_char(j.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS started_utc, "
                       "to_char(j.finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS finished_utc "
                       "FROM ingest.jobs j JOIN ingest.uploads u ON u.id = j.upload_id WHERE u.unit_id = ANY(:u) ORDER BY j.id DESC LIMIT :n",
                    u=vis, n=min(max(limit, 1), 200))
        steps = rows(c, "SELECT job_id, seq, name, state, extract(epoch FROM COALESCE(finished_at, now()) - started_at)::numeric(10,1)::float AS seconds "
                        "FROM ingest.job_steps WHERE job_id = ANY(:j) ORDER BY job_id, seq", j=[j["id"] for j in jobs])
    for j in jobs:
        j["steps"] = [{k: v for k, v in s.items() if k != "job_id"} for s in steps if s["job_id"] == j["id"]]
    return jobs
