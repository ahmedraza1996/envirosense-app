"""Assessments: run an engine on a scene, turn the result into GeoJSON-style records (plan section 10), cache it.

Geometry is in image pixel coordinates (x right, y down, 0-1024), which is what the map view draws on the image;
the label file's longitude/latitude polygon is kept as a property for map placement and reporting.
"""
import json
import threading
from datetime import datetime, timezone

import cv2
import numpy as np

from . import zones
from .engines import LABEL_IDS, REVIEW_CONFIDENCE, ROOT, XBD, class_name, discover_models, load_engine
from .scenes import CACHE, pixel_size_m, scene

STORE = ROOT / "runs" / "app" / "assessments"
COLOURS = {1: (52, 211, 153), 2: (250, 204, 21), 3: (251, 146, 60), 4: (239, 68, 68)}  # deck palette, RGB
_engines, _lock = {}, threading.Lock()


def models() -> dict:
    return discover_models()


def engine(model_id: str):
    with _lock:
        if model_id not in _engines:
            _engines[model_id] = load_engine(models()[model_id])
        return _engines[model_id]


def assessment_id(pair_id, model_id):
    return f"{pair_id}__{model_id}"


def lnglat_polygons(split, pair_id) -> dict:
    d = json.loads((XBD / split / "labels" / f"{pair_id}_post_disaster.json").read_text())
    return {f["properties"]["uid"]: f["wkt"] for f in d["features"]["lng_lat"]}


def to_feature(b, pair_id, model_id, mode, lnglat_wkt):
    from shapely import wkt as shp_wkt
    polys = b["polys"]
    rings = [[[round(x, 2), round(y, 2)] for x, y in p.exterior.coords] for p in polys]
    geom = {"type": "Polygon", "coordinates": rings[:1]} if len(rings) == 1 else \
        {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
    c = polys[0].centroid if len(polys) == 1 else max(polys, key=lambda p: p.area).centroid
    ll = shp_wkt.loads(lnglat_wkt) if lnglat_wkt else None
    llc = ll.centroid if ll is not None else None
    pred = class_name(b["predicted"])
    review = pred is None or b["confidence"] < REVIEW_CONFIDENCE
    reasons = (["not_detected"] if pred is None else []) + (["low_confidence"] if pred and b["confidence"] < REVIEW_CONFIDENCE else [])
    true = b["true_subtype"] if b["true_subtype"] in LABEL_IDS else None
    return {"type": "Feature", "id": b["uid"], "geometry": geom, "properties": {
        "building_id": b["uid"], "event_id": pair_id, "predicted_class": pred,
        "class_probabilities": {n: round(float(p), 4) for n, p in zip(zones.NAMES, b["probs"])},
        "confidence": round(b["confidence"], 4), "review_status": "needs_review" if review else "auto",
        "reason_codes": reasons, "true_class": true, "model_id": model_id, "inference_mode": mode,
        "centroid_px": [round(c.x, 2), round(c.y, 2)],
        "centroid_lnglat": [llc.x, llc.y] if llc is not None else None,
        "lnglat_wkt": lnglat_wkt, "localized_fraction": b.get("localized_fraction"),
        "invalid_polygon": b["invalid_polygon"]}}


def assess(pair_id: str, model_id: str, force: bool = False) -> dict:
    aid = assessment_id(pair_id, model_id)
    path = STORE / f"{aid}.json"
    if path.exists() and not force:
        return json.loads(path.read_text())
    sc = scene(pair_id)
    eng = engine(model_id)
    res = eng.assess(sc["split"], pair_id)
    ll = lnglat_polygons(sc["split"], pair_id)
    feats = [to_feature(b, pair_id, model_id, eng.mode, ll.get(b["uid"])) for b in res["buildings"]]
    zs, isolated = zones.priority_zones(feats, pixel_size_m(pair_id))
    has_map = "damage_map" in res
    record = {"id": aid, "pair_id": pair_id, "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
              "scene": sc, "model": {"id": model_id, "label": models()[model_id]["label"], "kind": eng.kind,
                                     "mode": eng.mode, **eng.info},
              "review_confidence_threshold": REVIEW_CONFIDENCE, "summary": zones.summarise(feats),
              "zones": zs, "isolated_severe": isolated, "scene_metrics": res["scene_metrics"],
              "has_damage_map": has_map, "type": "FeatureCollection", "features": feats}
    STORE.mkdir(parents=True, exist_ok=True)
    if has_map:
        rgba = np.zeros((*res["damage_map"].shape, 4), np.uint8)
        for k, rgb in COLOURS.items():
            m = res["damage_map"] == k
            rgba[m, :3], rgba[m, 3] = rgb, 150
        cv2.imwrite(str(STORE / f"{aid}_damage.png"), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    path.write_text(json.dumps(record))
    return record


def building_crop(pair_id: str, uid: str, phase: str, size: int = 256) -> bytes:
    """Evidence crop around one building (3x its size, as stored for training) with its outline, PNG bytes."""
    import build_crops
    sc = scene(pair_id)
    out = CACHE / "crops" / f"{pair_id}_{uid}_{phase}.png"
    if not out.exists():
        polys = next(p for u, _, p, _ in build_crops.read_features(sc["split"], pair_id) if u == uid)
        x, y, w, _ = build_crops.window(polys)
        img = cv2.cvtColor(cv2.imread(str(XBD / sc["split"] / "images" / f"{pair_id}_{phase}_disaster.png")), cv2.COLOR_BGR2RGB)
        patch = np.zeros((w, w, 3), np.uint8)
        sx0, sy0, sx1, sy1 = max(x, 0), max(y, 0), min(x + w, 1024), min(y + w, 1024)
        patch[sy0 - y:sy1 - y, sx0 - x:sx1 - x] = img[sy0:sy1, sx0:sx1]
        patch = cv2.resize(patch, (size, size), interpolation=cv2.INTER_CUBIC if w < size else cv2.INTER_AREA)
        s = size / w
        for p in polys:
            pts = np.round((np.asarray(p.exterior.coords) - (x, y)) * s).astype(np.int32)
            cv2.polylines(patch, [pts], True, (56, 189, 248), 2)
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), cv2.cvtColor(patch, cv2.COLOR_RGB2BGR))
    return out.read_bytes()
