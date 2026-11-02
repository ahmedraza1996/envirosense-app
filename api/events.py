"""Event view: every tile of a disaster, ranked by what the model found.

The benchmark hold set has several tiles per disaster. This module lists the disasters, ranks an event's tiles by
severely damaged roof area (area alerts of the chosen model), and runs the assessment of tiles not yet assessed as
one background job on the CPU, one tile at a time. An event can have close to a hundred tiles (about a minute each on this
server), so a job takes a batch spread evenly over the event rather than all of it. xBD label counts are returned for
scoring only.
"""
import json
import threading
import time

from . import service
from .scenes import catalogue, geotransforms

_job = {"state": "idle"}
_lock = threading.Lock()


def _record(pair_id, model_id):
    p = service.STORE / f"{pair_id}__{model_id}__area.json"
    return json.loads(p.read_text()) if p.exists() else None


def _tile_row(r, model_id):
    rec = _record(r.pair_id, model_id)
    row = {"pair_id": r.pair_id, "tile": r.pair_id.split("_")[-1], "centre_lat": r.centre_lat, "centre_lon": r.centre_lon,
           "xbd_buildings": int(r.buildings), "xbd_severe": int(r.severe_true), "assessed": rec is not None}
    if rec:
        al = rec["alerts"]
        row.update(alerts=len(al), high=sum(a["severity"] == "high" for a in al), medium=sum(a["severity"] == "medium" for a in al),
                   severe_m2=round(sum(a["severe_area_m2"] for a in al), 1), structures=rec["summary"]["buildings"])
    return row, rec


def list_events(model_id: str) -> list:
    df = catalogue()
    df = df[df.split == "hold"]
    out = []
    for name, g in df.groupby("disaster"):
        assessed = alerts = 0
        for r in g.itertuples():
            rec = _record(r.pair_id, model_id)
            if rec:
                assessed += 1
                alerts += len(rec["alerts"])
        out.append({"disaster": name, "disaster_type": g.disaster_type.iloc[0], "tiles": len(g), "assessed": assessed,
                    "alerts": alerts, "xbd_severe": int(g.severe_true.sum())})
    return sorted(out, key=lambda e: -e["xbd_severe"])


def detail(disaster: str, model_id: str) -> dict:
    df = catalogue()
    g = df[(df.split == "hold") & (df.disaster == disaster)]
    if g.empty:
        raise KeyError(disaster)
    tiles, alerts, frames = [], [], []
    for r in g.itertuples():
        row, rec = _tile_row(r, model_id)
        tiles.append(row)
        gt = geotransforms()[f"{r.pair_id}_post_disaster.png"][0]          # older stored records lack the geotransform
        ll = lambda x, y: [gt[0] + x * gt[1] + y * gt[2], gt[3] + x * gt[4] + y * gt[5]]
        frames.append({"pair_id": r.pair_id, "assessed": rec is not None, "ring": [ll(0, 0), ll(1024, 0), ll(1024, 1024), ll(0, 1024)]})
        if rec:
            for a in rec["alerts"]:
                alerts.append({"pair_id": r.pair_id, "alert_id": a["alert_id"], "severity": a["severity"],
                               "severe_m2": round(a["severe_area_m2"], 1), "ring": a.get("hull_lonlat") or [ll(x, y) for x, y in a["hull_px"]]})
    tiles.sort(key=lambda t: (-(t.get("severe_m2") or 0), -t["xbd_severe"]))
    for i, t in enumerate(tiles, 1):
        t["rank"] = i if t["assessed"] else None
    done = [t for t in tiles if t["assessed"]]
    rho = None
    if len(done) >= 4 and len({t["xbd_severe"] for t in done}) > 1 and len({t["severe_m2"] for t in done}) > 1:
        from scipy.stats import spearmanr
        rho = float(spearmanr([t["severe_m2"] for t in done], [t["xbd_severe"] for t in done])[0])
    return {"disaster": disaster, "model_id": model_id, "tiles": tiles, "alerts": alerts, "frames": frames,
            "rank_agreement_with_xbd": rho, "job": job_state(disaster)}


def job_state(disaster=None) -> dict:
    with _lock:
        j = dict(_job)
    return j if disaster in (None, j.get("disaster")) else {"state": "idle"}


def spread(items: list, n: int) -> list:
    """n items spread evenly over the list (all of it when n >= len)."""
    if n >= len(items):
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)] if n > 1 else items[:1]


def start(disaster: str, model_id: str, limit: int = 10) -> dict:
    df = catalogue()
    g = df[(df.split == "hold") & (df.disaster == disaster)]
    if g.empty:
        raise KeyError(disaster)
    todo = spread(sorted(r.pair_id for r in g.itertuples() if _record(r.pair_id, model_id) is None), max(1, limit))
    with _lock:
        if _job.get("state") == "running":
            return dict(_job)
        _job.clear()
        _job.update(state="running" if todo else "done", disaster=disaster, model_id=model_id, done=0, total=len(todo), current=None)
    if todo:
        threading.Thread(target=_run, args=(todo, disaster, model_id), daemon=True).start()
    return job_state()


def _run(todo, disaster, model_id):
    try:
        for i, pid in enumerate(todo):
            with _lock:
                _job.update(current=pid, done=i)
            service.assess_area(pid, model_id)
        with _lock:
            _job.update(state="done", done=len(todo), current=None)
    except Exception as e:  # noqa: BLE001  report on the job; the next start retries what is missing
        with _lock:
            _job.update(state="failed", error=f"{type(e).__name__}: {e}", current=None)
