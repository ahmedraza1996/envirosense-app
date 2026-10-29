"""Footprint-free area alerts.

Pipeline: the full-image U-Net marks building pixels and damage; connected building pixels become "structures"
(derived per run, never stored as a database); structures predicted major/destroyed are clustered; each cluster
raises one area alert. No building inventory is used as input; xBD outlines are used only to score benchmark tiles.

Alert rule (plan section 8 + user rule): severe-damage pixels within EPS_M of each other form one area;
  raise:    the area holds >= MIN_SEVERE_M2 of severely damaged roof
  severity: "high" if >= MAJORITY of the building area inside it is severely damaged, otherwise "medium"
"""
import hashlib

import cv2
import numpy as np

NAMES = ["no-damage", "minor-damage", "major-damage", "destroyed"]
SEVERE = ("major-damage", "destroyed")
MIN_AREA_PX = 25        # ignore specks (~5 m2 at 0.45 m/px)
EPS_M = 30.0            # damage within this distance belongs to one area
MIN_SEVERE_M2 = 250.0   # severely damaged roof area needed to raise an alert (about three houses)
MAJORITY = 0.5          # high severity when at least half of the building area is severely damaged
RULE = (f">= {MIN_SEVERE_M2:g} m2 of severely damaged roof with damage within {EPS_M:g} m; "
        f"high if >= {MAJORITY:.0%} of the building area is severely damaged")


def pixel_to_lonlat(gt, x, y):
    return gt[0] + x * gt[1] + y * gt[2], gt[3] + x * gt[4] + y * gt[5]


def structures(loc: np.ndarray, dmg: np.ndarray, dmg_prob: np.ndarray, gt, pixel_m: float) -> list:
    """Connected components of the predicted building mask, each with a majority damage class."""
    n, lab, stats, cent = cv2.connectedComponentsWithStats(loc.astype(np.uint8), connectivity=8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = stats[k]
        if area < MIN_AREA_PX:
            continue
        m = lab[y:y + h, x:x + w] == k
        votes = np.bincount(dmg[y:y + h, x:x + w][m] - 1, minlength=4)
        probs = dmg_prob[:, y:y + h, x:x + w][:, m].mean(1)
        cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        poly = cv2.approxPolyDP(c, 1.0, True).reshape(-1, 2) + (x, y)
        if len(poly) < 3:
            continue
        cx, cy = map(float, cent[k])
        out.append({"id": f"S{len(out) + 1:04d}", "polygon_px": poly.astype(float).tolist(), "centroid_px": [cx, cy],
                    "centroid_lonlat": list(pixel_to_lonlat(gt, cx, cy)), "area_m2": float(area * pixel_m ** 2),
                    "predicted": int(votes.argmax()), "probs": probs.tolist(), "confidence": float(probs.max()),
                    "mask_bbox": [int(x), int(y), int(w), int(h)], "label": int(k)})
    return out, lab


def area_alerts(loc: np.ndarray, dmg: np.ndarray, structs: list, pair_id: str, gt, pixel_m: float, model_id: str):
    """Alerts from damage *areas*, not structure centroids: touching buildings often merge into one detected
    structure, so centroid distances are unreliable. Severe-damage pixels are grown by EPS_M / 2 so that damage
    within EPS_M metres joins one area; an area raises an alert if it holds >= MIN_SEVERE_M2 of severely damaged roof.
    Severity uses the area share: high if >= MAJORITY of the building area inside it is severely damaged."""
    severe = (loc > 0) & (dmg >= 3)
    r = max(1, int(round(EPS_M / 2 / pixel_m)))
    grown = cv2.dilate(severe.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    n, lab = cv2.connectedComponents(grown, connectivity=8)
    cent = np.array([s["centroid_px"] for s in structs]) if structs else np.zeros((0, 2))
    cls = [NAMES[s["predicted"]] for s in structs]
    alerts, below = [], []
    for k in range(1, n):
        region = lab == k
        sev_px, bld_px = int((severe & region).sum()), int(((loc > 0) & region).sum())
        sev_m2 = sev_px * pixel_m ** 2
        inside = [i for i in range(len(structs)) if region[int(min(cent[i][1], 1023)), int(min(cent[i][0], 1023))]]
        ys, xs = np.nonzero(severe & region)
        cx, cy = float(xs.mean()), float(ys.mean())
        lon, lat = pixel_to_lonlat(gt, cx, cy)
        if sev_m2 < MIN_SEVERE_M2:
            below.append({"centroid_px": [cx, cy], "centroid_lat": lat, "centroid_lon": lon, "severe_m2": sev_m2})
            continue
        cnts, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        ring = cv2.approxPolyDP(max(cnts, key=cv2.contourArea), 2.0, True).reshape(-1, 2).astype(float).tolist()
        ring.append(ring[0])
        counts = {c: sum(cls[i] == c for i in inside) for c in NAMES}
        share = sev_px / bld_px if bld_px else 0.0
        alerts.append({
            "alert_id": "AL-" + hashlib.sha1(f"{pair_id}|{lat:.4f}|{lon:.4f}".encode()).hexdigest()[:8].upper(),
            "severity": "high" if share >= MAJORITY else "medium",
            "status": "draft: analyst review required", "rule": RULE,
            "severe_area_m2": sev_m2, "building_area_m2": bld_px * pixel_m ** 2, "severe_share": share,
            "structures": len(inside), "severe": counts["major-damage"] + counts["destroyed"], "counts": counts,
            "centroid_px": [cx, cy], "centroid_lat": lat, "centroid_lon": lon,
            "area_m2": float(region.sum() * pixel_m ** 2), "hull_px": ring,
            "hull_lonlat": [list(pixel_to_lonlat(gt, x, y)) for x, y in ring],
            "member_ids": [structs[i]["id"] for i in inside], "model_id": model_id,
            "priority": round(sev_m2 / 100, 1),   # ~ number of severely damaged 100 m2 roofs
        })
    alerts.sort(key=lambda a: (a["severity"] != "high", -a["severe_area_m2"]))
    return alerts, below


def benchmark(lab: np.ndarray, structs: list, label_polys: list) -> dict:
    """Benchmark tiles only: how many xBD buildings were found, and how many detections are real buildings."""
    if not label_polys:
        return {}
    inst = np.zeros(lab.shape, np.int32)
    for i, polys in enumerate(label_polys, 1):
        for p in polys:
            cv2.fillPoly(inst, [np.round(np.asarray(p.exterior.coords) * 16).astype(np.int32)], i, shift=4)
    found = lab > 0
    hit = 0
    for i in range(1, len(label_polys) + 1):
        m = inst == i
        if m.any() and found[m].mean() >= 0.5:
            hit += 1
    real = sum(1 for s in structs if (inst[lab == s["label"]] > 0).mean() >= 0.5)
    return {"xbd_buildings": len(label_polys), "xbd_found": hit, "recall": hit / len(label_polys),
            "detections": len(structs), "detections_on_buildings": real,
            "precision": real / len(structs) if structs else 0.0,
            "note": "Detections are connected building pixels; touching buildings can merge into one structure."}
