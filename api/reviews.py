"""Analyst review of area alerts, and export.

Every alert starts as a draft. An analyst confirms it, dismisses it, or asks for more information, optionally with a
note. Decisions are stored per assessment (runs/app/reviews/<assessment>.json) next to, never inside, the model output,
so re-running a model never erases them. Alert ids are derived from the tile and the alert's location, so they are
stable for the same result. Exports carry the decision with each alert; dismissed alerts are left out unless asked for.
"""
import csv
import io
import json
import threading
from datetime import datetime, timezone

from .engines import ROOT

STORE = ROOT / "runs" / "app" / "reviews"
STATUSES = ("pending", "confirmed", "dismissed", "needs_info")
NOTE_MAX = 500
_lock = threading.Lock()


class ReviewError(ValueError):
    pass


def _path(aid):
    return STORE / f"{aid}.json"


def load(aid: str) -> dict:
    p = _path(aid)
    return json.loads(p.read_text()) if p.exists() else {"alerts": {}}


def set_review(aid: str, rec: dict, alert_id: str, status: str, note: str = "", by: str = "analyst") -> dict:
    if status not in STATUSES:
        raise ReviewError(f"status must be one of {', '.join(STATUSES)}")
    if not any(a["alert_id"] == alert_id for a in rec.get("alerts") or []):
        raise KeyError(alert_id)
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise ReviewError(f"note is limited to {NOTE_MAX} characters")
    with _lock:
        data = load(aid)
        if status == "pending" and not note:
            data["alerts"].pop(alert_id, None)           # back to untouched
            entry = {"status": "pending", "note": "", "reviewed_by": None, "reviewed_utc": None}
        else:
            entry = {"status": status, "note": note, "reviewed_by": by,
                     "reviewed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
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
    inc = set(include or ("pending", "confirmed", "needs_info"))
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
                          "priority": a["priority"], "context_flags": c.get("flags", []),
                          "nearest_hospital": c.get("nearest_hospital"), "event": _title(sc),
                          "assessment_id": rec["id"], "model": rec["model"]["label"], "assessed_utc": rec["created_utc"]}})
    return {"type": "FeatureCollection", "name": f"alerts_{rec['id']}",
            "properties": {"event": _title(sc), "assessment_id": rec["id"], "model": rec["model"]["label"],
                           "rule": rec.get("alert_rule"), "status_included": sorted(set(include or ("pending", "confirmed", "needs_info"))),
                           "note": "Model output awaiting analyst review unless review_status says otherwise."},
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
    return {"type": "FeatureCollection", "name": f"structures_{rec['id']}", "features": feats}


CSV_COLUMNS = ["number", "alert_id", "severity", "review_status", "review_note", "reviewed_utc", "centroid_lat", "centroid_lon",
               "severe_roof_m2", "building_area_m2", "severe_share", "structures", "severe_structures", "area_m2", "priority",
               "context_flags", "nearest_hospital", "nearest_hospital_m", "event", "model", "assessed_utc"]


def alerts_csv(rec: dict, reviews: dict, include=None, context: dict | None = None) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, CSV_COLUMNS)
    w.writeheader()
    for f in alerts_geojson(rec, reviews, include, context)["features"]:
        p = dict(f["properties"])
        h = p.pop("nearest_hospital") or {}
        p["nearest_hospital"], p["nearest_hospital_m"] = h.get("name") or "", h.get("distance_m", "")
        p["context_flags"] = "; ".join(p["context_flags"])
        w.writerow({k: p.get(k, "") for k in CSV_COLUMNS})
    return out.getvalue()
