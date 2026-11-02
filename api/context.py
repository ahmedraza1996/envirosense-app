"""Priority context for area alerts: what is in and around each affected area, from OpenStreetMap (Overpass API).

Hospitals, clinics, schools, fire stations and police stations, and the main road network, are fetched once per
assessment (bounding box = the image plus a margin), cached on disk, and summarised per alert: facilities inside the
alert area, the nearest hospital, facilities within a kilometre and the distance to the nearest main road. Nothing here
changes an alert's severity; it tells the analyst what the damage may affect and how to get there. If the service is
unreachable the alerts are shown without context. Data (c) OpenStreetMap contributors, ODbL.
"""
import json
import math
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from shapely.geometry import LineString, Point, Polygon

from .scenes import CACHE

ENDPOINTS = [("https://overpass-api.de/api/interpreter", 90), ("https://overpass.private.coffee/api/interpreter", 20)]
USER_AGENT = "EnviroSense-damage-assessment/0.1 (capstone research prototype)"
MARGIN_DEG = 0.01            # about 1 km around the image
NEAR_M = 1000
KINDS = {"hospital": "Hospital", "clinic": "Clinic", "doctors": "Clinic", "school": "School", "kindergarten": "School",
         "college": "School", "university": "School", "fire_station": "Fire station", "police": "Police station"}
MAIN_ROADS = "motorway|trunk|primary|secondary|tertiary"
ROAD_NEAR_M = 300


def _query(query: str) -> dict:
    """Overpass answers GET requests more reliably than POST from some networks; slow answers are normal (queue)."""
    last = None
    for url, timeout in ENDPOINTS:
        try:
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode({"data": query}),
                                         headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001  try the next mirror
            last = e
    raise ConnectionError(f"OpenStreetMap service unreachable ({type(last).__name__})")


def _centre(el):
    if el["type"] == "node":
        return el["lat"], el["lon"]
    g = el.get("geometry")
    if g:
        return sum(p["lat"] for p in g) / len(g), sum(p["lon"] for p in g) / len(g)
    b = el.get("bounds")
    return ((b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2) if b else (None, None)


def fetch(south, west, north, east) -> dict:
    s, w, n, e = south - MARGIN_DEG, west - MARGIN_DEG, north + MARGIN_DEG, east + MARGIN_DEG
    box = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    amen = "|".join(KINDS)
    data = _query(f'[out:json][timeout:60];(nwr["amenity"~"^({amen})$"]{box};way["highway"~"^({MAIN_ROADS})$"]{box};);out geom tags;')
    facilities, ways = [], []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if "highway" in tags and el["type"] == "way":
            pts = [[p["lon"], p["lat"]] for p in el.get("geometry", [])]
            if len(pts) > 1:
                ways.append({"class": tags["highway"], "name": tags.get("name"), "pts": pts})
        elif tags.get("amenity") in KINDS:
            lat, lon = _centre(el)
            if lat is not None:
                facilities.append({"kind": KINDS[tags["amenity"]], "name": tags.get("name"), "lat": lat, "lon": lon,
                                   "id": f"{el['type']}/{el['id']}"})
    return {"facilities": facilities, "roads": ways, "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}


def _local(lat0):
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_574
    return lambda lon, lat: ((lon - 0) * kx, lat * ky)


def summarise(osm: dict, alerts: list) -> dict:
    """Per-alert context from fetched OSM data. Distances in metres, measured in a local flat projection."""
    out = {}
    for a in alerts:
        proj = _local(a["centroid_lat"])
        hull = Polygon([proj(x, y) for x, y in a["hull_lonlat"]]).buffer(0)
        inside, near, hospitals = [], [], []
        for f in osm["facilities"]:
            d = hull.distance(Point(proj(f["lon"], f["lat"])))
            if d == 0:
                inside.append(f)
            if d <= NEAR_M:
                near.append(f)
            if f["kind"] == "Hospital":
                hospitals.append((d, f))
        road = min(((LineString([proj(x, y) for x, y in r["pts"]]).distance(hull), r) for r in osm["roads"]),
                   key=lambda t: t[0], default=(None, None))
        hosp = min(hospitals, key=lambda t: t[0], default=(None, None))
        flags = []
        if any(f["kind"] in ("Hospital", "Clinic") for f in inside):
            flags.append("Health facility inside the affected area")
        if any(f["kind"] == "School" for f in inside):
            flags.append("School inside the affected area")
        if road[0] is not None and road[0] > ROAD_NEAR_M:
            flags.append(f"No main road within {ROAD_NEAR_M} m")
        count = lambda kind, fs: sum(1 for f in fs if f["kind"] == kind)
        out[a["alert_id"]] = {
            "inside": [{"kind": f["kind"], "name": f["name"]} for f in inside],
            "within_1km": {k: count(k, near) for k in ("Hospital", "Clinic", "School", "Fire station", "Police station")},
            "nearest_hospital": None if hosp[1] is None else {"name": hosp[1]["name"], "distance_m": round(hosp[0])},
            "nearest_main_road": None if road[1] is None else {"class": road[1]["class"], "name": road[1]["name"],
                                                               "distance_m": round(road[0])},
            "flags": flags}
    return out


_jobs: dict = {}
_lock = threading.Lock()


def _run(aid, rec, path):
    sc, alerts = rec["scene"], rec.get("alerts") or []
    gt, w, h = sc["geotransform"], sc.get("width_px") or sc.get("size_px") or 1024, sc.get("height_px") or sc.get("size_px") or 1024
    cs = [(gt[0] + x * gt[1] + y * gt[2], gt[3] + x * gt[4] + y * gt[5]) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
    try:
        osm = fetch(min(c[1] for c in cs), min(c[0] for c in cs), max(c[1] for c in cs), max(c[0] for c in cs))
        res = {"available": True, "source": "OpenStreetMap (Overpass API)", "fetched_utc": osm["fetched_utc"],
               "facilities": osm["facilities"], "alerts": summarise(osm, alerts)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res))
    except Exception as e:  # noqa: BLE001  offline demo, rate limit, timeout...
        res = {"available": False, "error": str(e), "facilities": [], "alerts": {}, "_t": time.time()}
    with _lock:
        _jobs[aid] = res


def for_assessment(aid: str, rec: dict, refresh: bool = False) -> dict:
    """Context for a stored area assessment: the cached result, or {"available": None} while it is being fetched in the
    background (Overpass can take a minute). Never raises: a failure comes back as available=False with the reason,
    and is retried on a request made more than two minutes later."""
    path = CACHE / "osm" / f"{aid}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    with _lock:
        job = _jobs.get(aid)
        if job is not None and not refresh and (job.get("available") is not False or time.time() - job["_t"] < 120):
            return job
        _jobs[aid] = {"available": None, "state": "loading"}
        threading.Thread(target=_run, args=(aid, rec, path), daemon=True).start()
        return _jobs[aid]
