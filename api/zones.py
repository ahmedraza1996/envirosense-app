"""Scene summary and priority zones (plan section 8).

Zones: DBSCAN over the centroids of buildings predicted major/destroyed, in metres (pixel coordinates times the
pixel size from the geotransform). Priority = 3 x destroyed + 2 x major + 0.5 x minor inside the zone (deck formula).
Severe buildings outside any cluster are kept as an "isolated" list, so sparse damage never disappears.
"""
import numpy as np
from shapely.geometry import MultiPoint, Point
from sklearn.cluster import DBSCAN
from sklearn.metrics import f1_score

NAMES = ["no-damage", "minor-damage", "major-damage", "destroyed"]
WEIGHTS = {"destroyed": 3.0, "major-damage": 2.0, "minor-damage": 0.5}


def summarise(features: list) -> dict:
    props = [f["properties"] for f in features]
    total = len(props)
    pred = [p["predicted_class"] for p in props]
    review = sum(p["review_status"] == "needs_review" for p in props)
    counts = {n: sum(c == n for c in pred) for n in NAMES}
    counts["not-detected"] = sum(c is None for c in pred)
    assessed = total - review
    severe = sum(1 for p in props if p["review_status"] != "needs_review" and p["predicted_class"] in ("major-damage", "destroyed"))
    true_counts = {n: sum(p["true_class"] == n for p in props) for n in NAMES}
    true_counts["un-classified"] = sum(p["true_class"] is None for p in props)
    pairs = [(NAMES.index(p["true_class"]), NAMES.index(p["predicted_class"]))
             for p in props if p["true_class"] in NAMES and p["predicted_class"] in NAMES]
    vs_truth = {}
    if pairs:
        t, q = map(np.array, zip(*pairs))
        present = sorted(set(t.tolist()))
        conf = np.zeros((4, 4), int)
        for a, b in pairs:
            conf[a, b] += 1
        vs_truth = {"buildings_compared": len(pairs), "accuracy": float((t == q).mean()),
                    "macro_f1_present_classes": float(f1_score(t, q, labels=present, average="macro", zero_division=0)),
                    "confusion": conf.tolist(), "confusion_labels": NAMES}
    return {"buildings": total, "assessed": assessed, "needs_review": review,
            "coverage": assessed / total if total else 0.0, "predicted": counts, "truth": true_counts,
            "severe_assessed": severe, "severe_share": severe / assessed if assessed else 0.0, "vs_truth": vs_truth}


def priority_zones(features: list, pixel_size_m: float, eps_m: float = 30.0, min_samples: int = 3):
    cent = np.array([f["properties"]["centroid_px"] for f in features], float) if features else np.zeros((0, 2))
    cls = [f["properties"]["predicted_class"] for f in features]
    severe = [i for i, c in enumerate(cls) if c in ("major-damage", "destroyed")]
    if not severe:
        return [], []
    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(cent[severe] * pixel_size_m)
    zones, isolated = [], []
    for k in sorted(set(labels) - {-1}):
        members = [severe[j] for j, l in enumerate(labels) if l == k]
        hull = MultiPoint([tuple(cent[i]) for i in members]).convex_hull.buffer(10 / pixel_size_m)  # 10 m margin
        inside = [i for i in range(len(features)) if hull.covers(Point(*cent[i]))]
        counts = {n: sum(cls[i] == n for i in inside) for n in NAMES}
        lnglat = np.array([features[i]["properties"]["centroid_lnglat"] for i in members])
        zones.append({"zone_id": "", "buildings": len(inside), "counts": counts,
                      "priority": sum(WEIGHTS.get(n, 0) * counts[n] for n in NAMES),
                      "centroid_px": [float(v) for v in cent[members].mean(0)],
                      "centroid_lat": float(lnglat[:, 1].mean()), "centroid_lon": float(lnglat[:, 0].mean()),
                      "hull_px": [list(map(float, xy)) for xy in hull.exterior.coords],
                      "member_ids": [features[i]["properties"]["building_id"] for i in members]})
    zones.sort(key=lambda z: -z["priority"])
    for n, z in enumerate(zones, 1):
        z["zone_id"] = f"Z{n}"
    for j, l in enumerate(labels):
        if l == -1:
            p = features[severe[j]]["properties"]
            isolated.append({"building_id": p["building_id"], "predicted_class": p["predicted_class"],
                             "centroid_px": p["centroid_px"], "centroid_lat": p["centroid_lnglat"][1],
                             "centroid_lon": p["centroid_lnglat"][0]})
    return zones, isolated
