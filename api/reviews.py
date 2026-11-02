"""Analyst review of area alerts, and export.

Every alert starts as a draft. An analyst confirms it, dismisses it, or asks for more information, optionally with a
note. Decisions are stored per assessment (runs/app/reviews/<assessment>.json) next to, never inside, the model output,
so re-running a model never erases them. Alert ids are derived from the tile and the alert's location, so they are
stable for the same result. Exports carry the decision with each alert; dismissed and retracted alerts are left out unless asked for.

Every decision is kept: an entry has the current status and a history of all earlier ones (who, when, status, note). A reviewer name is
required, a dismissal needs a reason, and an alert that was confirmed and later found wrong is retracted (with a reason), not deleted.
"""
import csv
import io
import json
import threading
from datetime import datetime, timezone

from .engines import ROOT

STORE = ROOT / "runs" / "app" / "reviews"
STATUSES = ("pending", "proposed", "confirmed", "dismissed", "needs_info", "retracted")
DEFAULT_INCLUDE = ("pending", "proposed", "confirmed", "needs_info")
NOTE_MAX = 500
_lock = threading.Lock()


class ReviewError(ValueError):
    pass


def _path(aid):
    return STORE / f"{aid}.json"


def load(aid: str) -> dict:
    p = _path(aid)
    return json.loads(p.read_text()) if p.exists() else {"alerts": {}}


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
    if role not in ("analyst", "officer"):
        raise PermissionError("this role cannot review alerts")
    if len(note) > NOTE_MAX:
        raise ReviewError(f"note is limited to {NOTE_MAX} characters")
    if status in ("dismissed", "retracted") and not note:
        raise ReviewError(f"a reason is required to {'dismiss' if status == 'dismissed' else 'retract'} an alert")
    with _lock:
        data = load(aid)
        old = data["alerts"].get(alert_id) or {}
        if status == "retracted" and old.get("status") != "confirmed":
            raise ReviewError("only a confirmed alert can be retracted")
        if status in ("confirmed", "retracted") and role != "officer":
            raise PermissionError(f"only an approving officer can {'confirm' if status == 'confirmed' else 'retract'} an alert")
        if status == "confirmed":
            if old.get("status") != "proposed":
                raise ReviewError("an alert is confirmed from a proposal: someone proposes it first, then an officer confirms")
            if old.get("proposed_by") == by:
                raise ReviewError("you proposed this alert yourself; a different officer must confirm it")
        if old.get("status") == "proposed" and status == "pending" and not note:
            raise ReviewError("a reason is required to return a proposal")
        utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        history = list(old.get("history") or [])
        history.append({"status": status, "note": note, "by": by, "role": role, "unit": unit, "utc": utc})
        entry = {"status": status, "note": note, "reviewed_by": None if status == "pending" else by,
                 "reviewed_utc": None if status == "pending" else utc, "history": history,
                 "proposed_by": by if status == "proposed" else (old.get("proposed_by") if status == "confirmed" else None)}
        data["alerts"][alert_id] = entry
        STORE.mkdir(parents=True, exist_ok=True)
        tmp = _path(aid).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(_path(aid))
    return entry


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
