"""Registers assessments and their alerts in the database (core.assessments, core.alerts).

The full record (structures, outlines, provenance) is a file next to the damage map; the database holds what is listed, scoped, reviewed
and traced: which scene or upload, which model version, the thresholds and provenance used, and each alert with its outline as a PostGIS
geometry. Reviews hang on the alert rows, so a decision can only exist for an alert that exists.
"""
import hashlib
import json
from pathlib import Path

from shapely.geometry import MultiPoint, Polygon, mapping

from ..db.engine import one, run, tx
from .engines import ROOT


def _polygon(ring) -> dict | None:
    """The alert outline as a valid GeoJSON polygon, or None when it is degenerate (a line or a point)."""
    try:
        pts = [(float(x), float(y)) for x, y in ring]
        g = Polygon(pts)
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty or g.geom_type != "Polygon":
            g = MultiPoint(pts).convex_hull
        return mapping(g) if g.geom_type == "Polygon" and not g.is_empty else None
    except (TypeError, ValueError):
        return None


def register(rec: dict, record_path: Path | None = None, created_by: str | None = None) -> None:
    """Create or refresh the rows of an assessment. Alerts that already have a review are never removed."""
    scene = rec.get("scene") or {}
    upload = rec["pair_id"] if scene.get("source") == "upload" else None
    kind = "upload" if upload else ("area" if rec.get("kind") == "area" else "benchmark")
    prov = rec.get("provenance") or {}
    sha = (((prov.get("checkpoint") or {}).get("sha256")) or None)
    alerts = rec.get("alerts") or []
    pts = [(x, y) for a in alerts for x, y in a.get("hull_lonlat", [])]
    hull = MultiPoint(pts).convex_hull if len(pts) >= 3 else None
    foot = mapping(hull) if hull is not None and hull.geom_type == "Polygon" else None      # footprint: hull of all alert outlines
    path = str(record_path.relative_to(ROOT)) if record_path and record_path.is_absolute() and ROOT in record_path.parents else (str(record_path) if record_path else f"runs/app/assessments/{rec['id']}.json")
    with tx() as c:
        mv = one(c, "SELECT id FROM sem.model_versions WHERE id = :m", m=rec["model"]["id"])
        run(c, "INSERT INTO core.assessments (id, kind, upload_id, scene, model_id, model_version_id, record_path, record_sha256, thresholds, provenance, n_alerts, footprint, created_by) "
               "VALUES (:id, :kind, :up, :scene, :model, :mv, :path, :sha, CAST(:th AS jsonb), CAST(:pv AS jsonb), :n, "
               "CASE WHEN CAST(:foot AS text) IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(CAST(:foot AS text)), 4326) END, :by) "
               "ON CONFLICT (id) DO UPDATE SET model_version_id = :mv, record_sha256 = :sha, thresholds = CAST(:th AS jsonb), provenance = CAST(:pv AS jsonb), "
               "n_alerts = :n, footprint = EXCLUDED.footprint",
            id=rec["id"], kind=kind, up=upload, scene=rec["pair_id"], model=rec["model"]["id"], mv=mv["id"] if mv else None, path=path, sha=sha,
            th=json.dumps(prov.get("thresholds") or {}), pv=json.dumps(prov, default=str), n=len(alerts), foot=json.dumps(foot) if foot else None, by=created_by)
        ids = []
        for a in alerts:
            ids.append(a["alert_id"])
            g = _polygon(a.get("hull_lonlat") or [])
            run(c, "INSERT INTO core.alerts (assessment_id, alert_id, severity, priority, severe_share, area_m2, structures, severe_structures, geom, props) "
                   "VALUES (:a, :i, :sev, :pr, :sh, :ar, :st, :ss, CASE WHEN CAST(:g AS text) IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(CAST(:g AS text)), 4326) END, CAST(:p AS jsonb)) "
                   "ON CONFLICT (assessment_id, alert_id) DO UPDATE SET severity = :sev, priority = :pr, severe_share = :sh, area_m2 = :ar, structures = :st, "
                   "severe_structures = :ss, geom = EXCLUDED.geom, props = CAST(:p AS jsonb)",
                a=rec["id"], i=a["alert_id"], sev=a["severity"], pr=a.get("priority"), sh=a.get("severe_share"), ar=a.get("area_m2"), st=a.get("structures"),
                ss=a.get("severe"), g=json.dumps(g) if g else None,
                p=json.dumps({k: a.get(k) for k in ("severe_area_m2", "building_area_m2", "centroid_lat", "centroid_lon", "low_confidence_structures", "low_confidence_share")}))
        run(c, "DELETE FROM core.alerts a WHERE a.assessment_id = :a AND a.alert_id <> ALL(:ids) "
               "AND NOT EXISTS (SELECT 1 FROM wf.alert_reviews r WHERE r.assessment_id = a.assessment_id AND r.alert_id = a.alert_id)", a=rec["id"], ids=ids)


def is_registered(aid: str) -> bool:
    with tx() as c:
        return bool(one(c, "SELECT 1 AS x FROM core.assessments WHERE id = :a", a=aid))


def record_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
