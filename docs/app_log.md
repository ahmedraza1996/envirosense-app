# App log

Changes to the damage-assessment app (`app/`), newest last. Model experiments are in `experiment_log.md`.

## A01 MVP: scene + damage map, building inspector, summary + priority zones (2026-10-29)

**Scope (user choices):** both model families selectable, the first three features, VM + SSH tunnel, React.

**Backend** (`app/api/`, FastAPI):
- `engines.py`: the crop classifiers (`clf_B` = B_r18_official, `clf_A` = A_r18_official) and full-image U-Nets
  (`unet_post` = S_r34_post; `unet_early` = S_r34_early, listed once its run has test results). CPU inference with
  2 torch threads and one inference at a time, so it never competes with training for the GPUs.
- `scenes.py`: catalogue of the 763 hold-split scenes that contain buildings (of 933 hold pairs) (true class counts, dates, pixel size, centre).
- `zones.py`: summary (counts, coverage, needs-review, severe share, check against xBD labels) and priority zones
  (DBSCAN over major/destroyed centroids, 30 m, min 3; priority = 3·destroyed + 2·major + 0.5·minor; isolated severe
  buildings kept).
- `service.py`: assessments as GeoJSON-style records (plan §10 fields), cached in `runs/app/assessments/`, with the
  model's run, checkpoint, epoch and git commit; U-Net pixel damage map as a PNG overlay.
- `main.py`: `/api/models`, `/api/scenes`, `/api/scenes/{id}` (+ `/image/{pre|post}`, `/buildings/{uid}/crop/{pre|post}`),
  `POST /api/assess`, `/api/assessments/{id}` (+ `/summary`, `/damage-map`); serves the React build at `/`.
- `src/data.py` refactor: crop geometry and image preparation moved into `crop_box`, `prep_image`, `model_input`,
  shared by training and the app.

**Frontend** (`app/web/`, React 18 + TypeScript + Vite + Leaflet, deck mockup styling): scene list with true damage
mix, model selector, damage map over the 1024 px image (before/after, xBD-truth outlines, errors only, zones, U-Net
pixel map), summary panel (KPIs, check vs xBD with confusion matrix, priority zones that zoom the map, provenance),
building inspector (before/after crops, probability bars, review status, xBD label, location).

**Verification:**
- Classifier parity: app probabilities equal the saved evaluation predictions of B and A on 3 hold scenes each
  (same class for every building, max difference < 0.001).
- U-Net parity: the app's scene xView2 score equals `seg_benchmark.evaluate` exactly.
- Zones (synthetic clusters + isolated building) and every API route tested (pytest, 8 tests passing).
- `tsc --noEmit` and `vite build` pass.

**Run:** `app/scripts/app.sh` (uvicorn on 127.0.0.1:8000), then on the Mac `ssh -N -L 8000:127.0.0.1:8000 EnviroSense`
and open http://localhost:8000. Queued after E12 by `app/scripts/next_app.sh` (pre-computes demo scenes first).

**Known limits:** probabilities are uncalibrated; the review threshold (0.6) is a placeholder; demo scenes come from
xBD hold tiles (unseen tiles, but the same events as training); no report export, review queue, routing or agents yet.

## A02 UI redesign (2026-10-29)

**Why:** the first UI read as generic AI output: a dark navy and cyan theme, a row of status chips, uppercase
eyebrow labels on every section, a side-tab accent on the selected row, six equal-weight KPI cards, floating
button clusters on the map and permanent labels on every zone. Impeccable's published anti-pattern list was used as
the checklist (the plugin itself is not installed here).

**Change:** light, neutral, map-first layout; saturated colour only for damage data (muted green, amber, orange,
red ramp). Header reduced to a breadcrumb and the model picker. Scene list: search, disaster filter, sort, plain rows.
Right panel: one headline figure (buildings with major damage or destroyed), one distribution bar, a plain class
table, priority areas as a ranked table, agreement with xBD as a few figures and a shaded confusion matrix. Map:
Before/After switch and a single Layers menu; only the five highest-priority areas are outlined and numbered.
Checked in the browser at 1440 × 900 on Santa Rosa and Harvey tiles.

## A03 Situation report (2026-10-29)

**What:** one-click report per assessment, `api/report.py`. Formats: printable HTML (A4, "Print or save as PDF"),
Markdown download, and a map figure (after image with assessed damage and the five priority areas numbered).
Routes: `/api/assessments/{id}/report.html`, `/report.md`, `/report-map.png`. "Situation report" and "Markdown"
actions at the top of the summary panel.

**Content:** draft status (analyst review required before external use), a summary built only from the numbers,
area and imagery (tile extent, centre, dates, pixel size), damage by building, priority areas with centre
coordinates, isolated severe buildings (first 10), buildings needing review (lowest confidence first, first 15),
method and limits (model, run, checkpoint, epoch, commit; uncalibrated scores; imagery-only damage classes; no road,
casualty or population information; agreement with xBD where labels exist).

**Safeguards:** every figure comes from the stored assessment; the report refuses to render (HTTP 500) if class
counts do not add up to the building total; small non-zero shares show as "<1%".

**Verification:** `tests/test_report.py` (numbers match the record, inconsistent counts refused, all three routes
render); 8 backend tests pass; report checked in the browser for Harvey tile 00000149.

## A04 Footprint-free area alerts (2026-10-29)

**Why:** the per-building view depends on a building inventory (xBD outlines), which does not exist for a real
disaster area, and responders need one alert per affected area, not per building.

**What:** "Area alerts" mode, now the default (`api/alerts.py`, `service.assess_area`, `POST /api/assess-area`).
The full-image U-Net marks building pixels and damage; connected building pixels become structures (derived per
run, never stored as an inventory). Severe-damage pixels are grown by 15 m so damage within 30 m joins one area; an
area raises an alert if it holds >= 250 m2 of severely damaged roof; severity is high when >= 50% of the building
area there is severely damaged. Each alert: stable ID, centre lat/lon from the image georeferencing, outline,
severe roof area, share, extent, structure counts, status "draft: analyst review required". xBD outlines are used
only for a separate benchmark check (buildings found, detection precision). The per-building view remains as
"Building check".

**Design change during build:** the first version clustered structure centroids (DBSCAN); the U-Net merges rows
of touching houses into one structure (Santa Rosa: 271 buildings -> 54 structures), which split a burnt
neighbourhood into 4 small alerts and 41 isolated blobs. Clustering damage areas instead gives one high alert for
that neighbourhood.

**Also:** alert-based situation report; evidence crops for any feature (`/api/assessments/{id}/features/{fid}/crop/{phase}`);
fixed `scripts/precompute_demo.py`, whose quotes had been stripped when it was created (it would have crashed after E12).

**Verification:** synthetic alert tests (grouping, threshold, severity, stable IDs), area report test, full suite
14 passed; checked in the browser on Santa Rosa (1 high alert) and Palu (6 alerts: 4 high, 2 medium).

## A05 Geographic map view (2026-10-29)

**What:** an Image | Map switch on the map (`web/src/components/GeoMap.tsx`). Map shows an OpenStreetMap
basemap with the satellite tile placed by its own georeferencing (GDAL geotransform, EPSG:4326), detected
structures and numbered alert areas in real coordinates, and every other tile of the set as a dot at its location
(coloured by its xBD damage share; click to open). Scenes now carry their centre coordinates and geotransform.

**Note:** placement uses the image geotransform; the label files' own lon/lat polygons differ from it by ~9 m
(audit), so outlines may sit a few metres off OSM features. OSM tiles are fetched by the viewer's browser
(attribution shown).

**Access:** the local tunnel now uses port 8765 (`ssh -N -L 127.0.0.1:8765:127.0.0.1:8000 EnviroSense`, then
http://127.0.0.1:8765), because a Docker container on the Mac already listens on 8000.

**Verification:** build passes; checked in the browser on Santa Rosa: tile aligned with surrounding OSM streets,
alert area drawn, overview dots for the other Santa Rosa tiles.
