"""Situation report for one stored assessment: Markdown, printable HTML, and a static map figure.

Every number comes from the stored assessment record (no free text is generated, no LLM). The report is marked
DRAFT: the plan requires analyst review before anything is shared externally.
"""
import html
import json
from datetime import datetime, timezone

import cv2
import numpy as np

from .engines import XBD
from .service import STORE

NAMES = ["destroyed", "major-damage", "minor-damage", "no-damage"]
LABEL = {"destroyed": "Destroyed", "major-damage": "Major damage", "minor-damage": "Minor damage",
         "no-damage": "No visible damage", "not-detected": "Not detected"}
BGR = {"no-damage": (95, 143, 63), "minor-damage": (32, 165, 217), "major-damage": (43, 98, 217),
       "destroyed": (30, 38, 179), None: (132, 140, 143)}
MAX_ISOLATED = 10   # keep the brief short; the app lists every building
MAX_REVIEW = 15


class ReportError(ValueError):
    pass


def load(aid: str) -> dict:
    path = STORE / f"{aid}.json"
    if not path.exists():
        raise FileNotFoundError(aid)
    return json.loads(path.read_text())


def share(n: int, total: int) -> str:
    """Percent of total; small non-zero shares show as <1% rather than a misleading 0%."""
    x = n / total if total else 0.0
    return "<1%" if 0 < x < 0.005 else f"{x:.0%}"


def title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split("-"))


def latlon(lat, lon) -> str:
    return f"{abs(lat):.5f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.5f}°{'E' if lon >= 0 else 'W'}"


def facts(a: dict) -> dict:
    """Everything the report states, derived once from the record and checked for internal consistency."""
    s, sc = a["summary"], a["scene"]
    pred = s["predicted"]
    total = s["buildings"]
    if sum(pred.values()) != total:
        raise ReportError(f"class counts {sum(pred.values())} do not add up to {total} buildings")
    severe = pred["destroyed"] + pred["major-damage"]
    side_km = sc.get("size_px", 1024) * sc["pixel_size_m"] / 1000
    feats = [f["properties"] for f in a["features"]]
    review = sorted((p for p in feats if p["review_status"] == "needs_review"), key=lambda p: p["confidence"])
    return {"a": a, "s": s, "sc": sc, "pred": pred, "total": total, "severe": severe, "side_km": side_km,
            "review": review, "zones": a["zones"], "isolated": a["isolated_severe"],
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


def summary_sentences(f: dict) -> list:
    p, total = f["pred"], f["total"]
    out = [f"Of {total} buildings in the assessed tile, {f['severe']} ({share(f['severe'], total)}) are assessed as "
           f"destroyed ({p['destroyed']}) or with major damage ({p['major-damage']}); {p['minor-damage']} show minor "
           f"damage and {p['no-damage']} no visible damage."]
    if f["zones"]:
        z = f["zones"][0]
        out.append(f"Severe damage concentrates in {len(f['zones'])} priority area{'s' if len(f['zones']) != 1 else ''}; "
                   f"area 1 (around {latlon(z['centroid_lat'], z['centroid_lon'])}) contains {z['counts']['destroyed']} "
                   f"destroyed and {z['counts']['major-damage']} major-damage buildings.")
    if f["isolated"]:
        out.append(f"{len(f['isolated'])} severely damaged building{'s are' if len(f['isolated']) != 1 else ' is'} "
                   "outside any cluster and listed individually.")
    n = len(f["review"])
    out.append(f"{n} building{'s' if n != 1 else ''} need{'' if n != 1 else 's'} analyst review before these figures are used."
               if n else "No buildings were flagged for review.")
    return out


def fmt_area(m2: float) -> str:
    return f"{m2 / 10000:.1f} ha" if m2 >= 10000 else f"{m2:,.0f} m²"


def area_markdown(aid: str, f: dict) -> str:
    """Footprint-free report: one entry per area alert; no building inventory involved."""
    a, sc, p = f["a"], f["sc"], f["pred"]
    m, alerts, b = a["model"], a.get("alerts", []), a.get("benchmark") or {}
    high = sum(x["severity"] == "high" for x in alerts)
    if alerts:
        x = alerts[0]
        lead = (f"{len(alerts)} area alert{'s' if len(alerts) != 1 else ''} ({high} high, {len(alerts) - high} medium). "
                f"Alert 1 ({x['severity']}) around {latlon(x['centroid_lat'], x['centroid_lon'])}: "
                f"{fmt_area(x['severe_area_m2'])} of severely damaged roof, {x['severe_share']:.0%} of the building area "
                f"there, over an extent of {fmt_area(x['area_m2'])}.")
    else:
        lead = "No area meets the alert rule on this tile."
    sev = p["destroyed"] + p["major-damage"]
    upload = sc.get("source") == "upload"
    heading = sc["name"] if upload else f"{title(sc['disaster'])}, tile {a['pair_id'].split('_')[-1]}"
    L = [f"# Situation report: {heading}", "",
         "**Status: DRAFT, analyst review required before external use.**  ",
         f"Area alerts for assessment `{aid}` · assessed {a['created_utc']} UTC · generated {f['generated']}", "",
         "## Summary", "",
         f"{lead} The model found {f['total']} structures in the image, {sev} of them with major damage or destroyed. "
         "No building inventory was used.", "",
         "## Area and imagery", ""] + (upload_lines(a, sc) if upload else [
         f"- Event: {title(sc['disaster'])} ({sc['disaster_type']})",
         f"- Tile: {a['pair_id']}, about {f['side_km']:.2f} × {f['side_km']:.2f} km, centred at {latlon(sc['centre_lat'], sc['centre_lon'])}",
         f"- Imagery: before {sc['pre_date']}, after {sc['post_date']}, {sc['pixel_size_m']:.2f} m per pixel"]) + ["",
         "## Area alerts", ""]
    if alerts:
        L += [f"Rule: {a.get('alert_rule', '')}.", "",
              "| # | Alert | Severity | Centre | Severe roof | Share | Extent | Structures |",
              "|---:|---|---|---|---:|---:|---:|---:|"]
        for i, x in enumerate(alerts, 1):
            L.append(f"| {i} | {x['alert_id']} | {x['severity'].capitalize()} | {latlon(x['centroid_lat'], x['centroid_lon'])} | "
                     f"{fmt_area(x['severe_area_m2'])} | {x['severe_share']:.0%} | {fmt_area(x['area_m2'])} | {x['structures']} |")
    else:
        L.append("None.")
    if a.get("below_threshold"):
        L += ["", f"{len(a['below_threshold'])} smaller patches of severe damage are below the alert threshold and are not alerted."]
    L += ["", "## Detected structures", "", "| Class | Structures |", "|---|---:|"]
    for c in NAMES:
        L.append(f"| {LABEL[c]} | {p[c]} |")
    L += [f"| **Total** | **{f['total']}** |", "",
          "## Method and limits", "",
          f"- Model: {m['label']} ({m['mode']}), run `{m['run']}`, epoch {m['epoch'] + 1}, checkpoint `{m['checkpoint']}`, "
          f"code commit {m['git_commit'][:12] if not m['git_commit'].startswith('not') else 'not recorded'}.",
          "- Structures are connected building pixels found by the model in the image; touching buildings can merge, so "
          "structure counts are not building counts.",
          "- Alert locations come from the image's own georeferencing.",
         ("- A post-only model misses many completely destroyed buildings (nothing recognisable is left on the after "
          "image); a before image fixes this." if "post-only" in m["mode"] or "after only" in m["mode"] else
          "- Buildings are located with the before image, damage is read from the after image."),
          "- Damage classes describe what is visible from above; they are not field-verified structural assessments.",
          "- The report has no information on road access, casualties or population."]
    if b:
        L.append(f"- Benchmark check (xBD tile, not used for the alerts): {b['xbd_found']} of {b['xbd_buildings']} xBD "
                 f"buildings found ({b['recall']:.0%}); {b['precision']:.0%} of detections are on buildings.")
    L += ["", "---", f"Generated by EnviroSense from stored assessment `{aid}`. Figures are computed, not edited."]
    return "\n".join(L) + "\n"


def upload_lines(a: dict, sc: dict) -> list:
    b = sc.get("before") or {}
    w, h, m = sc["width_px"], sc["height_px"], sc["pixel_size_m"]
    if b.get("kind") == "archive":
        tiles = b.get("tiles", [])
        src = (f"{len(tiles)} archive image{'s' if len(tiles) != 1 else ''} ({b['archive']}, captured {sc['pre_date']})"
               if tiles else "none found in the archive")
    else:
        src = "uploaded with the after image"
    L = [f"- Upload: {sc['name']} ({sc['disaster_type']}), {a['pair_id']}",
         f"- Area: about {w * m / 1000:.2f} × {h * m / 1000:.2f} km, centred at {latlon(sc['centre_lat'], sc['centre_lon'])}, "
         f"{m:.2f} m per pixel",
         f"- After image: event date {sc['post_date']}",
         f"- Before image: {src}; covers {b.get('coverage', 0):.0%} of the area"]
    if b.get("shift_m") is not None:
        L.append(f"- Alignment: before/after offset measured at {b['shift_m']:.1f} m"
                 + (", corrected" if b.get("corrected") else ", within tolerance" if b["shift_m"] < 1 else ", not corrected"))
    L += [f"- Note: {n}" for n in sc.get("notes", [])]
    return L


def markdown(aid: str) -> str:
    f = facts(load(aid))
    if f["a"].get("kind") == "area":
        return area_markdown(aid, f)
    a, sc, p, total = f["a"], f["sc"], f["pred"], f["total"]
    m = a["model"]
    L = [f"# Situation report: {title(sc['disaster'])}, tile {a['pair_id'].split('_')[-1]}", "",
         f"**Status: DRAFT, analyst review required before external use.**  ",
         f"Report for assessment `{aid}` · assessed {a['created_utc']} UTC · generated {f['generated']}", "",
         "## Summary", "", " ".join(summary_sentences(f)), "",
         "## Area and imagery", "",
         f"- Event: {title(sc['disaster'])} ({sc['disaster_type']})",
         f"- Tile: {a['pair_id']}, about {f['side_km']:.2f} × {f['side_km']:.2f} km, centred at {latlon(sc['centre_lat'], sc['centre_lon'])}",
         f"- Imagery: before {sc['pre_date']}, after {sc['post_date']}, {sc['pixel_size_m']:.2f} m per pixel", "",
         "## Damage by building", "", "| Class | Buildings | Share |", "|---|---:|---:|"]
    for c in NAMES + (["not-detected"] if p.get("not-detected") else []):
        L.append(f"| {LABEL[c]} | {p[c]} | {share(p[c], total)} |")
    L += [f"| **Total** | **{total}** | 100% |", "", "## Priority areas", ""]
    if f["zones"]:
        L += ["Clusters of destroyed and major-damage buildings within 30 m of each other, ranked by "
              "3 × destroyed + 2 × major + 0.5 × minor.", "",
              "| # | Destroyed | Major | Minor | Buildings | Score | Centre |", "|---:|---:|---:|---:|---:|---:|---|"]
        for i, z in enumerate(f["zones"], 1):
            c = z["counts"]
            L.append(f"| {i} | {c['destroyed']} | {c['major-damage']} | {c['minor-damage']} | {z['buildings']} | "
                     f"{z['priority']:g} | {latlon(z['centroid_lat'], z['centroid_lon'])} |")
    else:
        L.append("No clusters of severe damage in this tile.")
    if f["isolated"]:
        L += ["", f"**Isolated severe buildings** ({len(f['isolated'])}):", "", "| Building | Class | Location |", "|---|---|---|"]
        for b in f["isolated"][:MAX_ISOLATED]:
            L.append(f"| {b['building_id'][:8]} | {LABEL[b['predicted_class']]} | {latlon(b['centroid_lat'], b['centroid_lon'])} |")
        if len(f["isolated"]) > MAX_ISOLATED:
            L.append(f"| … | {len(f['isolated']) - MAX_ISOLATED} more in the app | |")
    L += ["", "## Buildings needing review", ""]
    if f["review"]:
        L += [f"{len(f['review'])} buildings, lowest confidence first.", "",
              "| Building | Model call | Confidence | Reason | Location |", "|---|---|---:|---|---|"]
        for r in f["review"][:MAX_REVIEW]:
            loc = latlon(r["centroid_lnglat"][1], r["centroid_lnglat"][0]) if r["centroid_lnglat"] else "n/a"
            L.append(f"| {r['building_id'][:8]} | {LABEL.get(r['predicted_class'] or 'not-detected')} | {r['confidence']:.0%} | "
                     f"{', '.join(x.replace('_', ' ') for x in r['reason_codes'])} | {loc} |")
        if len(f["review"]) > MAX_REVIEW:
            L.append(f"| … | {len(f['review']) - MAX_REVIEW} more in the app | | | |")
    else:
        L.append("None.")
    v = f["s"]["vs_truth"]
    L += ["", "## Method and limits", "",
          f"- Model: {m['label']} ({m['mode']}), run `{m['run']}`, epoch {m['epoch'] + 1}, checkpoint `{m['checkpoint']}`, "
          f"code commit {m['git_commit'][:12] if not m['git_commit'].startswith('not') else 'not recorded'}.",
          f"- Building outlines come from the xBD annotations; each outline is assessed from satellite imagery only.",
          f"- Buildings are flagged for review when model confidence is below {a['review_confidence_threshold']:.0%}"
          + (" or the building was not detected." if p.get("not-detected") else "."),
          "- Confidence values are uncalibrated model scores, not probabilities of structural failure.",
          "- Damage classes describe what is visible from above; they are not field-verified structural assessments.",
          "- The report has no information on road access, casualties or population."]
    if v.get("buildings_compared"):
        L.append(f"- Benchmark check (this tile has xBD labels): {v['accuracy']:.0%} of {v['buildings_compared']} buildings "
                 f"agree with xBD; macro-F1 {v['macro_f1_present_classes']:.2f}.")
    L += ["", "---", f"Generated by EnviroSense from stored assessment `{aid}`. Figures are computed, not edited."]
    return "\n".join(L) + "\n"


def map_png(aid: str) -> bytes:
    """After image with predicted damage outlines and numbered priority areas (cached)."""
    out = STORE / f"{aid}_report_map.png"
    if out.exists():
        return out.read_bytes()
    a = load(aid)
    from .service import record_image
    img = cv2.cvtColor(record_image(a, "post"), cv2.COLOR_RGB2BGR)
    overlay = img.copy()
    for feat in a["features"]:
        g = feat["geometry"]
        rings = g["coordinates"] if g["type"] == "Polygon" else [r[0] for r in g["coordinates"]]
        pts = [np.round(np.array(r)).astype(np.int32) for r in rings]
        cv2.fillPoly(overlay, pts, BGR[feat["properties"]["predicted_class"]])
    img = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)
    areas = a.get("alerts", []) if a.get("kind") == "area" else a["zones"][:5]
    for i, z in enumerate(areas, 1):
        hull = np.round(np.array(z["hull_px"])).astype(np.int32)
        cv2.polylines(img, [hull], True, (25, 27, 28), 2, cv2.LINE_AA)
        cx, cy = map(int, z["centroid_px"])
        cv2.circle(img, (cx, cy), 15, (25, 27, 28), -1, cv2.LINE_AA)
        cv2.putText(img, str(i), (cx - 6 if i < 10 else cx - 11, cy + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(out), img)
    return out.read_bytes()


def to_html(aid: str) -> str:
    """Printable HTML rendering of the Markdown report (A4, 'Save as PDF' from the browser)."""
    md = markdown(aid)
    body, table, in_list = [], [], False

    def inline(t):
        t = html.escape(t)
        while "**" in t:
            t = t.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
        while "`" in t:
            t = t.replace("`", "<code>", 1).replace("`", "</code>", 1)
        return t

    def flush_table():
        if not table:
            return
        rows = [r.strip("|").split("|") for r in table if not set(r.replace("|", "").strip()) <= set("-: ")]
        align = ["num" if c.strip().endswith(":") else "" for c in table[1].strip("|").split("|")] if len(table) > 1 else []
        h = "".join(f"<th class='{align[i] if i < len(align) else ''}'>{inline(c.strip())}</th>" for i, c in enumerate(rows[0]))
        b = "".join("<tr>" + "".join(f"<td class='{align[i] if i < len(align) else ''}'>{inline(c.strip())}</td>"
                                     for i, c in enumerate(r)) + "</tr>" for r in rows[1:])
        body.append(f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>")
        table.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if in_list and not line.startswith("- "):
            body.append("</ul>")
            in_list = False
        if line.startswith("# "):
            body.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            sec = line[3:]
            body.append(f"<h2>{inline(sec)}</h2>")
            if sec == "Area and imagery":
                what = "area alerts numbered" if "Area alerts for assessment" in md else "the five highest-priority areas numbered"
                body.append(f"<figure><img src='/api/assessments/{aid}/report-map.png' alt='Damage map'>"
                            "<figcaption>After image with assessed damage (green none, amber minor, orange major, red "
                            f"destroyed) and {what}.</figcaption></figure>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(line[2:])}</li>")
        elif line.strip() == "---":
            body.append("<hr>")
        elif line.strip():
            body.append(f"<p>{inline(line.rstrip('  '))}</p>")
    flush_table()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Situation report {html.escape(aid)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap">
<style>
:root {{ --ink:#1C1B19; --ink2:#4A4842; --ink3:#7A776F; --line:#E4E2DC; }}
body {{ margin:0; background:#F6F5F2; color:var(--ink); font:13px/1.55 Inter,-apple-system,sans-serif; font-feature-settings:"tnum" 1; }}
.page {{ max-width:780px; margin:24px auto; background:#fff; padding:44px 52px; border:1px solid var(--line); }}
.bar {{ max-width:780px; margin:24px auto 0; display:flex; justify-content:flex-end; gap:8px; }}
.bar button, .bar a {{ font:inherit; font-weight:500; padding:6px 12px; border:1px solid #CFCCC4; border-radius:6px; background:#fff; color:var(--ink2); text-decoration:none; cursor:pointer; }}
h1 {{ font-size:22px; letter-spacing:-.01em; margin:0 0 6px; }}
h2 {{ font-size:14px; margin:26px 0 8px; padding-top:14px; border-top:1px solid var(--line); }}
p {{ margin:6px 0; }} ul {{ margin:6px 0; padding-left:18px; }} li {{ margin:2px 0; }}
table {{ width:100%; border-collapse:collapse; margin:8px 0; font-size:12px; }}
th {{ text-align:left; color:var(--ink3); font-weight:500; border-bottom:1px solid var(--line); padding:5px 6px; }}
td {{ padding:5px 6px; border-bottom:1px solid #F0EEE9; }} .num {{ text-align:right; }}
code {{ font-family:"JetBrains Mono",Menlo,monospace; font-size:11px; color:var(--ink2); }}
figure {{ margin:10px 0 4px; }} figure img {{ width:100%; display:block; border-radius:4px; }}
figcaption {{ color:var(--ink3); font-size:11.5px; margin-top:6px; }}
hr {{ border:0; border-top:1px solid var(--line); margin:24px 0 10px; }}
@media print {{ body {{ background:#fff; }} .bar {{ display:none; }} .page {{ border:0; margin:0; padding:0; max-width:none; }}
  h2 {{ break-after:avoid; }} table, figure {{ break-inside:avoid; }} @page {{ size:A4; margin:16mm; }} }}
</style></head><body>
<div class="bar"><a href="/api/assessments/{aid}/report.md" download>Download Markdown</a><button onclick="window.print()">Print or save as PDF</button></div>
<article class="page">{''.join(body)}</article></body></html>"""
