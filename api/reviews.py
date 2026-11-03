"""Analyst review of area alerts, and export.

Every alert starts as a draft. An analyst proposes it, dismisses it, or asks for more information, optionally with a note; a different
approving officer confirms a proposal. Decisions are rows in PostgreSQL (wf.alert_reviews: the current state, wf.alert_review_events: every
step, never edited) next to, never inside, the model output, so re-running a model never erases them. Alert ids are derived from the tile and
the alert's location, so they are stable for the same result. Exports carry the decision with each alert; dismissed and retracted alerts are
left out unless asked for.

Every decision is kept: an entry has the current status and a history of all earlier ones (who, when, status, note). A reviewer name is
required, a dismissal needs a reason, and an alert that was confirmed and later found wrong is retracted (with a reason), not deleted.
The four-eyes rule and the reason rule are checked here for a clear message and again by the database as constraints.
"""
import csv
import io
from datetime import timezone

import sqlalchemy as sa
from sqlalchemy import exc as sa_exc

from ..db.engine import one, rows, run, tx
from . import auth, registry

STATUSES = ("pending", "proposed", "confirmed", "dismissed", "needs_info", "retracted")
DEFAULT_INCLUDE = ("pending", "proposed", "confirmed", "needs_info")
NOTE_MAX = 500
_STAMP = "%Y-%m-%d %H:%M:%S"


class ReviewError(ValueError):
    pass


def _utc(t):
    return t.astimezone(timezone.utc).strftime(_STAMP) if t else None


def load(aid: str) -> dict:
    """{"alerts": {alert_id: entry}} for an assessment; an alert without a row is pending."""
    out = {}
    with tx() as c:
        for r in rows(c, "SELECT alert_id, status, note, reviewed_by, reviewed_at, proposed_by FROM wf.alert_reviews WHERE assessment_id = :a", a=aid):
            out[r["alert_id"]] = {"status": r["status"], "note": r["note"], "reviewed_by": r["reviewed_by"], "reviewed_utc": _utc(r["reviewed_at"]),
                                  "proposed_by": r["proposed_by"], "history": []}
        for e in rows(c, "SELECT alert_id, status, note, actor, role, unit_id, at FROM wf.alert_review_events WHERE assessment_id = :a ORDER BY alert_id, seq", a=aid):
            if e["alert_id"] in out:
                out[e["alert_id"]]["history"].append({"status": e["status"], "note": e["note"], "by": e["actor"], "role": e["role"], "unit": e["unit_id"], "utc": _utc(e["at"])})
    return {"alerts": out}


def set_review(aid: str, rec: dict, alert_id: str, status: str, note: str = "", by: str = "", role: str = "officer", unit: str = "") -> dict:
    """Four-eyes rule: only an officer confirms, and only an alert another person proposed. An analyst proposes, dismisses or asks for information."""
    if status not in STATUSES:
        raise ReviewError(f"status must be one of {', '.join(STATUSES)}")
    if not any(a["alert_id"] == alert_id for a in rec.get("alerts") or []):
        raise KeyError(alert_id)
    by = (by or "").strip()
    note = (note or "").strip()
    if not by:
        raise ReviewError("a reviewer is required")
    perms = auth.perms_of(role)
    if "review" not in perms:
        raise PermissionError("this role cannot review alerts")
    if len(note) > NOTE_MAX:
        raise ReviewError(f"note is limited to {NOTE_MAX} characters")
    if status in ("dismissed", "retracted") and not note:
        raise ReviewError(f"a reason is required to {'dismiss' if status == 'dismissed' else 'retract'} an alert")
    if not registry.is_registered(aid):
        registry.register(rec, created_by=by)
    try:
        with tx() as c:
            old = one(c, "SELECT status, proposed_by FROM wf.alert_reviews WHERE assessment_id = :a AND alert_id = :i FOR UPDATE", a=aid, i=alert_id) or {}
            if status == "retracted" and old.get("status") != "confirmed":
                raise ReviewError("only a confirmed alert can be retracted")
            if status in ("confirmed", "retracted") and "approve" not in perms:
                raise PermissionError(f"only an approving officer can {'confirm' if status == 'confirmed' else 'retract'} an alert")
            if status == "confirmed":
                if old.get("status") != "proposed":
                    raise ReviewError("an alert is confirmed from a proposal: someone proposes it first, then an officer confirms it")
                if old.get("proposed_by") == by:
                    raise ReviewError("you proposed this alert yourself; a different officer must confirm it")
            if old.get("status") == "proposed" and status == "pending" and not note:
                raise ReviewError("a reason is required to return a proposal")
            proposed_by = by if status == "proposed" else (old.get("proposed_by") if status == "confirmed" else None)
            run(c, "INSERT INTO wf.alert_reviews (assessment_id, alert_id, status, note, reviewed_by, reviewed_at, proposed_by) "
                   "VALUES (:a, :i, :s, :n, CASE WHEN :s = 'pending' THEN NULL ELSE CAST(:b AS text) END, CASE WHEN :s = 'pending' THEN NULL ELSE now() END, :p) "
                   "ON CONFLICT (assessment_id, alert_id) DO UPDATE SET status = :s, note = :n, "
                   "reviewed_by = CASE WHEN :s = 'pending' THEN NULL ELSE CAST(:b AS text) END, reviewed_at = CASE WHEN :s = 'pending' THEN NULL ELSE now() END, "
                   "proposed_by = :p, version = wf.alert_reviews.version + 1",
                a=aid, i=alert_id, s=status, n=note, b=by, p=proposed_by)
            run(c, "INSERT INTO wf.alert_review_events (assessment_id, alert_id, seq, status, note, actor, role, unit_id) "
                   "SELECT :a, :i, COALESCE(MAX(seq), 0) + 1, :s, :n, :b, :r, :u FROM wf.alert_review_events WHERE assessment_id = :a AND alert_id = :i",
                a=aid, i=alert_id, s=status, n=note, b=by, r=role, u=unit)
    except sa_exc.IntegrityError as e:
        raise ReviewError("the database refused this change: " + str(getattr(e.orig, "diag", None) and e.orig.diag.message_primary or "constraint violated")) from e
    return load(aid)["alerts"][alert_id]


def entry(reviews: dict, alert_id: str) -> dict:
    return reviews["alerts"].get(alert_id) or {"status": "pending", "note": "", "reviewed_by": None, "reviewed_utc": None}


def counts(rec: dict, reviews: dict) -> dict:
    c = dict.fromkeys(STATUSES, 0)
    for a in rec.get("alerts") or []:
        c[entry(reviews, a["alert_id"])["status"]] += 1
    return c


def _keep(rec, reviews, include):
    inc = set(include or DEFAULT_INCLUDE)
    bad = inc - set(STATUSES)
    if bad:
        raise ReviewError(f"unknown status {', '.join(sorted(bad))}")
    return [(i, a, entry(reviews, a["alert_id"])) for i, a in enumerate(rec.get("alerts") or [], 1)
            if entry(reviews, a["alert_id"])["status"] in inc]


def _title(sc):
    return sc.get("name") or f"{sc.get('disaster', '')} {sc.get('pair_id', '')}".strip()


def alerts_geojson(rec: dict, reviews: dict, include=None, context: dict | None = None) -> dict:
    sc = rec["scene"]
    ctx = (context or {}).get("alerts", {})
    feats = []
    for i, a, r in _keep(rec, reviews, include):
        c = ctx.get(a["alert_id"]) or {}
        feats.append({"type": "Feature", "id": a["alert_id"],
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in a["hull_lonlat"]]]},
                      "properties": {
                          "alert_id": a["alert_id"], "number": i, "severity": a["severity"], "review_status": r["status"],
                          "review_note": r["note"], "reviewed_utc": r["reviewed_utc"],
                          "severe_roof_m2": round(a["severe_area_m2"], 1), "building_area_m2": round(a["building_area_m2"], 1),
                          "severe_share": round(a["severe_share"], 3), "structures": a["structures"],
                          "severe_structures": a["severe"], "area_m2": round(a["area_m2"], 1),
                          "centroid_lat": round(a["centroid_lat"], 6), "centroid_lon": round(a["centroid_lon"], 6),
                          "priority": a["priority"], "low_confidence_structures": a.get("low_confidence_structures"), "low_confidence_share": a.get("low_confidence_share"), "context_flags": c.get("flags", []),
                          "nearest_hospital": c.get("nearest_hospital"), "event": _title(sc),
                          "assessment_id": rec["id"], "model": rec["model"]["label"], "assessed_utc": rec["created_utc"],
                          "checkpoint_sha256": ((rec.get("provenance") or {}).get("checkpoint") or {}).get("sha256"),
                          "after_sha256": (((rec.get("provenance") or {}).get("inputs") or {}).get("after") or {}).get("sha256"),
                          "before_sha256": (((rec.get("provenance") or {}).get("inputs") or {}).get("before") or {}).get("sha256"),
                          "review_confidence": ((rec.get("provenance") or {}).get("thresholds") or {}).get("review_confidence"),
                          "quality_flags": [g["code"] for g in rec.get("gates") or [] if g["level"] == "warn"],
                          "position_offset_m": (sc.get("geo_offset_m") or {}).get("east") is not None and
                          [(sc.get("geo_offset_m") or {}).get("east"), (sc.get("geo_offset_m") or {}).get("north")] or None}})
    return {"type": "FeatureCollection", "name": f"alerts_{rec['id']}",
            "properties": {"event": _title(sc), "assessment_id": rec["id"], "model": rec["model"]["label"],
                           "rule": rec.get("alert_rule"), "status_included": sorted(set(include or DEFAULT_INCLUDE)),
                           "note": "DRAFT: model output awaiting analyst review unless review_status says otherwise. Visible damage only; verify in the field. "
                                   "Not for dispatch or safety decisions (governance/intended_use.md).",
                           "gates": rec.get("gates") or [], "provenance": rec.get("provenance")},
            "features": feats}


def structures_geojson(rec: dict) -> dict:
    """Detected structures placed with the image's geotransform (linear fit for projected images)."""
    gt = rec["scene"]["geotransform"]
    ll = lambda x, y: [round(gt[0] + x * gt[1] + y * gt[2], 7), round(gt[3] + x * gt[4] + y * gt[5], 7)]
    feats = []
    for f in rec["features"]:
        ring = f["geometry"]["coordinates"][0]
        p = f["properties"]
        feats.append({"type": "Feature", "id": f["id"], "geometry": {"type": "Polygon", "coordinates": [[ll(x, y) for x, y in ring]]},
                      "properties": {"id": f["id"], "predicted_class": p["predicted_class"], "confidence": p["confidence"],
                                     "area_m2": p.get("area_m2"), "review_status": p["review_status"]}})
    return {"type": "FeatureCollection", "name": f"structures_{rec['id']}",
            "properties": {"note": "DRAFT: structures detected by a model, visible damage only; verify in the field.",
                           "gates": rec.get("gates") or [], "provenance": rec.get("provenance")}, "features": feats}


CSV_COLUMNS = ["number", "alert_id", "severity", "review_status", "review_note", "reviewed_utc", "centroid_lat", "centroid_lon",
               "severe_roof_m2", "building_area_m2", "severe_share", "structures", "severe_structures", "area_m2", "priority", "low_confidence_structures", "low_confidence_share",
               "context_flags", "nearest_hospital", "nearest_hospital_m", "event", "model", "assessed_utc", "checkpoint_sha256", "after_sha256", "before_sha256", "review_confidence", "quality_flags",
               "position_offset_m"]


def alerts_csv(rec: dict, reviews: dict, include=None, context: dict | None = None) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, CSV_COLUMNS)
    w.writeheader()
    for f in alerts_geojson(rec, reviews, include, context)["features"]:
        p = dict(f["properties"])
        h = p.pop("nearest_hospital") or {}
        p["nearest_hospital"], p["nearest_hospital_m"] = h.get("name") or "", h.get("distance_m", "")
        p["context_flags"] = "; ".join(p["context_flags"])
        p["quality_flags"] = "; ".join(p.get("quality_flags") or [])
        p["position_offset_m"] = "" if not p.get("position_offset_m") else f"{p['position_offset_m'][0]:+.1f} E, {p['position_offset_m'][1]:+.1f} N"
        w.writerow({k: p.get(k, "") for k in CSV_COLUMNS})
    return out.getvalue()
