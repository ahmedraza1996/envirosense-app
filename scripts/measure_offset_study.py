"""How far is each xBD tile from the street map, and how much does that vary? (proposal experiment X8)

For tiles spread over every event of the hold split (3 per event, the ones with the most buildings), the OpenStreetMap buildings are drawn into the
image grid and slid over the image edges (app/api/geocal.measure: the same method as the Align menu). One row per tile: measured east and north offset
in metres, how sharp the match is, how much the before and after images disagree, whether the match is called clear, how many OSM buildings were used.
Tiles without enough OpenStreetMap buildings or an unreachable Overpass service are listed with the reason, not dropped.

  uv run --no-sync python app/scripts/measure_offset_study.py [--per-event 3]
Output: reports/offset_study.csv and reports/offset_study.md
"""
import argparse, csv, json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cv2  # noqa: E402

from app.api import geocal  # noqa: E402
from app.api.scenes import catalogue, scene  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-event", type=int, default=3)
    p.add_argument("--pause", type=float, default=6.0, help="seconds between Overpass requests")
    a = p.parse_args()
    cat = catalogue()
    cat = cat[(cat.split == "hold") & (cat.buildings >= 40)]
    pids = []
    for _, g in cat.groupby("disaster"):
        pids += g.sort_values("buildings", ascending=False).pair_id.iloc[: a.per_event].tolist()
    print(len(pids), "tiles", flush=True)
    rows = []
    for k, pid in enumerate(pids, 1):
        sc = scene(pid)
        rec = {"scene": {"geotransform": sc["geotransform"], "pixel_size_m": sc["pixel_size_m"], "centre_lat": sc["centre_lat"]}}
        image_for = lambda ph, sc=sc, pid=pid: cv2.cvtColor(cv2.imread(str(ROOT / "data/xbd" / sc["split"] / "images" / f"{pid}_{ph}_disaster.png")), cv2.COLOR_BGR2RGB)
        row = {"pair_id": pid, "disaster": sc["disaster"], "xbd_buildings": sc["buildings"]}
        for attempt in range(3):
            try:
                m = geocal.measure(rec, image_for)
                row.update(east_m=m["east_m"], north_m=m["north_m"], osm_buildings=m["buildings"], sharpness=m["sharpness"],
                           before_after_disagree_m=m["before_after_disagree_m"], clear=m["clear"], error="")
                break
            except ValueError as e:                      # too few OSM buildings: not retried
                row.update(error=str(e)); break
            except ConnectionError as e:
                row.update(error=str(e)); time.sleep(30)
        rows.append(row)
        print(k, pid, {x: row.get(x) for x in ("east_m", "north_m", "sharpness", "clear", "error")}, flush=True)
        time.sleep(a.pause)
    cols = ["pair_id", "disaster", "xbd_buildings", "osm_buildings", "east_m", "north_m", "sharpness", "before_after_disagree_m", "clear", "error"]
    out = ROOT / "reports"
    with (out / "offset_study.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in cols} for r in rows)
    ok = [r for r in rows if r.get("east_m") not in (None, "")]
    clear = [r for r in ok if r["clear"]]
    mag = lambda r: (r["east_m"] ** 2 + r["north_m"] ** 2) ** 0.5
    L = ["# Street-map offset study (X8)", "",
         f"{len(rows)} hold tiles ({a.per_event} per event, most buildings); measured: {len(ok)}; called a clear match: {len(clear)}; not measurable: {len(rows) - len(ok)}.", ""]
    for name, sel in (("all measured tiles", ok), ("clear matches only", clear)):
        if len(sel) >= 3:
            e, n = [r["east_m"] for r in sel], [r["north_m"] for r in sel]
            L += [f"**{name}** (n = {len(sel)}): median east {statistics.median(e):+.1f} m, median north {statistics.median(n):+.1f} m; "
                  f"offset length median {statistics.median(map(mag, sel)):.1f} m, 90th percentile {sorted(map(mag, sel))[int(0.9 * (len(sel) - 1))]:.1f} m, maximum {max(map(mag, sel)):.1f} m; "
                  f"spread of east {statistics.pstdev(e):.1f} m, of north {statistics.pstdev(n):.1f} m.", ""]
    L += ["| tile | event | OSM buildings | east m | north m | sharpness | disagree m | clear | note |", "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for r in rows:
        L.append(f"| {r['pair_id']} | {r['disaster']} | {r.get('osm_buildings', '')} | {r.get('east_m', '')} | {r.get('north_m', '')} | {r.get('sharpness', '')} | "
                 f"{r.get('before_after_disagree_m', '')} | {r.get('clear', '')} | {r.get('error', '')} |")
    (out / "offset_study.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:6]))


if __name__ == "__main__":
    main()
