"""Map offset: put an assessment's image, outlines and alerts on the street map where they really are.

xBD tiles carry an approximate geotransform (measured on Hurricane Harvey tile 5: the OpenStreetMap building outlines sit about
20 m from the roofs in the image), and any georeference can be a few metres off against the street map. The outlines always fit the
image; only the placement of image + outlines + alerts on the map moves. The offset is a plain translation (east, north in metres)
applied to every coordinate of the stored record, kept in `scene["geo_offset_m"]` so it can be changed or removed again.

`measure` suggests an offset: OpenStreetMap building outlines are drawn into the image grid and moved over a window of shifts to
where they lie on the strongest image edges (the same method as `snap`). Its peak sharpness says how much to trust it; the analyst
confirms or adjusts it by eye.
"""
import json
import math

import cv2
import numpy as np

from . import context, snap

M_PER_DEG = 110_574.0        # one degree of latitude
LIMIT_M = 150.0              # largest offset accepted
WINDOW_M = 30.0              # search window (+- m) when measuring
CROP_M = 1500.0              # measure on the central square of at most this size (keeps the Overpass request small)
MAX_PX = 1536                # measured at no more than this many pixels a side
CLEAR_PEAK = 1.10            # sharpness at or above which the OSM edges give a clear answer
KEYS_LAT, KEYS_LON = ("centroid_lat", "centre_lat"), ("centroid_lon", "centre_lon")


def _deg(lat: float, east_m: float, north_m: float) -> tuple[float, float]:
    return east_m / (M_PER_DEG * math.cos(math.radians(lat))), north_m / M_PER_DEG


def current(rec: dict) -> dict:
    return rec["scene"].get("geo_offset_m") or {"east": 0.0, "north": 0.0, "method": None}


def _shift(o, dlon: float, dlat: float):
    """Translate every longitude / latitude field of a stored record, in place."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k in KEYS_LAT and isinstance(v, (int, float)):
                o[k] = v + dlat
            elif k in KEYS_LON and isinstance(v, (int, float)):
                o[k] = v + dlon
            elif k in ("hull_lonlat", "centroid_lnglat", "centroid_lonlat") and v:
                o[k] = [[p[0] + dlon, p[1] + dlat] for p in v] if isinstance(v[0], (list, tuple)) else [v[0] + dlon, v[1] + dlat]
            elif k == "geotransform" and v:
                o[k] = [v[0] + dlon, *v[1:3], v[3] + dlat, *v[4:]]
            elif k == "geo_bounds" and v:
                o[k] = [[p[0] + dlat, p[1] + dlon] for p in v]            # Leaflet order: [lat, lon]
            elif k == "lnglat_wkt":
                continue                                                  # building-mode outlines are not drawn from it
            else:
                _shift(v, dlon, dlat)
    elif isinstance(o, list):
        for v in o:
            _shift(v, dlon, dlat)


def set_offset(rec: dict, east_m: float, north_m: float, method: str, note: str | None = None) -> dict:
    """Make the record's placement `east_m` / `north_m` metres from where the file's own georeference puts it (absolute, not
    relative to the previous offset). Returns the offset entry."""
    if math.hypot(east_m, north_m) > LIMIT_M:
        raise ValueError(f"offset of more than {LIMIT_M:.0f} m refused")
    prev = current(rec)
    dlon, dlat = _deg(rec["scene"].get("centre_lat") or 0.0, east_m - prev["east"], north_m - prev["north"])
    _shift(rec, dlon, dlat)
    entry = {"east": round(east_m, 2), "north": round(north_m, 2), "method": method if (east_m or north_m) else None}
    if note:
        entry["note"] = note
    rec["scene"]["geo_offset_m"] = entry
    return entry


def _osm_buildings(rec: dict, west: float, south: float, east: float, north: float) -> list:
    box = f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"
    data = context._query(f'[out:json][timeout:60];way["building"]{box};out geom;')
    return [el["geometry"] for el in data.get("elements", []) if len(el.get("geometry", [])) >= 3]


def measure(rec: dict, image_for) -> dict:
    """Suggest the offset (absolute east / north in metres) that puts the image on the OpenStreetMap buildings.
    `image_for(phase)` returns the RGB image of the assessment. Raises ValueError when it cannot be measured."""
    sc = rec["scene"]
    gt = sc.get("geotransform")
    if not gt or abs(gt[2]) > 1e-9 or abs(gt[4]) > 1e-9 or sc.get("geo_bounds"):
        raise ValueError("measuring needs a north-up image; use the arrows to align a rotated one by eye")
    pre = image_for("pre")
    h, w = pre.shape[:2]
    pix = sc["pixel_size_m"]
    half = int(min(w, h, CROP_M / pix) // 2)
    x0, y0 = int(w // 2 - half), int(h // 2 - half)
    f = min(1.0, MAX_PX / (2 * half))
    px = lambda lon, lat: ((lon - gt[0]) / gt[1] - x0, (lat - gt[3]) / gt[5] - y0)      # image px -> crop px
    west, north = gt[0] + x0 * gt[1], gt[3] + y0 * gt[5]
    east, south = west + 2 * half * gt[1], north + 2 * half * gt[5]
    ways = _osm_buildings(rec, west, south, east, north)
    if len(ways) < 8:
        raise ValueError(f"only {len(ways)} OpenStreetMap buildings in this image; too few to measure against")
    side = int(2 * half * f)
    mask = np.zeros((side, side), np.uint8)
    for g in ways:
        pts = np.array([px(p["lon"], p["lat"]) for p in g]) * f
        cv2.fillPoly(mask, [np.round((pts - 0.5) * 16).astype(np.int32)], 1, shift=4)
    r = int(min(80, max(8, round(WINDOW_M / (pix / f)))))
    res = {}
    for phase in ("pre", "post"):
        img = image_for(phase)[y0:y0 + 2 * half, x0:x0 + 2 * half]
        img = cv2.resize(img, (side, side), interpolation=cv2.INTER_AREA)
        res[phase] = snap.peak(snap.surface(mask.astype(bool), snap.edge_strength(img), r), r)
    dx, dy, sharp = res["pre"]                       # the outlines follow the before image
    # the OSM outlines have to move by (dx, dy) crop px onto the image, i.e. the image has to move by (-dx, -dy) to meet them
    mx, my = -dx / f * pix, dy / f * pix             # metres east, north (image rows run south)
    east_m, north_m = current(rec)["east"] + mx, current(rec)["north"] + my
    agree = math.hypot((res["pre"][0] - res["post"][0]) / f * pix, (res["pre"][1] - res["post"][1]) / f * pix)
    clear = sharp >= CLEAR_PEAK and res["post"][2] >= CLEAR_PEAK and agree <= 8.0
    return {"east_m": round(east_m, 1), "north_m": round(north_m, 1), "buildings": len(ways), "sharpness": round(sharp, 2),
            "before_after_disagree_m": round(agree, 1), "clear": bool(clear),
            "note": ("The street-map buildings fit the image edges clearly at this shift." if clear else
                     "The match is weak (few buildings, trees or flooding): check the result by eye before keeping it.")}
