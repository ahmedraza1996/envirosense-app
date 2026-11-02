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

## A06 - Upload workflow (after image -> before image -> alerts)
- Upload an after image (GeoTIFF, or PNG/JPEG with corner coordinates) plus name, disaster type and optional event date (`POST /api/uploads`; processed one job at a time on CPU in a background thread; `GET /api/uploads[/{id}]` for status).
- Before image: uploaded by the user, or found by location in the xBD before-image archive (STRtree over 11k georeferenced pre tiles, captured before the event date), mosaicked onto the after image grid (`api/archive.py`, `api/imagery.py`).
- Alignment check: phase correlation on smoothed, halved images (raw phase correlation failed on JPEG copies); offsets of 1.5-48 px are corrected, weak peaks are reported as unmeasurable. xBD pairs themselves are 1-25 px misregistered.
- Inference: tiled 1024 windows with overlap (`UNetEngine.predict_large`, equal to `predict_maps` on one tile); pre+post where the before image covers the ground, post-only elsewhere. Alerts code now takes any pixel->lon/lat function and image size.
- UI: Benchmark tiles | Uploads tabs, upload dialog, before-image section (source, coverage, offset), size-aware image and map views.
- Tests: 19 passing, including upload-vs-benchmark parity, archive lookup, injected 8 px offset, JPEG upload via API.
- Samples: `scripts/make_sample_uploads.py` -> runs/app/samples (GeoTIFF, JPEG + corners, offset GeoTIFF).

## A07 - Map and Before/After views
- Map view shows damage on the street map: the satellite photo is now an optional layer ("Satellite image" in Layers, off by default); alert areas are filled by severity; the assessed tile extent is a dotted frame.
- Before/After: damage colours appear only on After. Before shows the buildings the model found as neutral blue outlines (and hides alert areas), so the two views no longer look like the same result on different photos.
- index.html is served with no-cache, so a new build shows on the next reload.
- The default model is the best test score (E14 Siamese, 0.591); E14 is registered as unet_paired_ext.

## A08 - Pair upload with coordinates, metadata file, demo set
- The before image can carry its own corner coordinates (`before_west/south/east/north`); a plain before image with no coordinates of its own and no after-image corners is refused with a clear message.
- Upload dialog reads an optional `metadata.json` (name, disaster type, event date, after/before corners) and fills the form; corner inputs for the before image with a "Same as after image" shortcut.
- `scripts/make_demo_set.py` builds `demo_set/`: eight xBD hold scenarios, each with `pre/post.tif` (embedded georeferencing), `pre/post.jpg`, `metadata.json`; README with the demo walkthrough and truth for the presenter. `scripts/run_demo_set.py` pushes every scenario through the upload API (GeoTIFF or JPEG route).
- Checked end to end on all eight scenarios (E14 model). GeoTIFF and JPEG routes measure the same before/after offset; JPEG compression changes structure counts.

## A09 - Alignment, learned registration, review and export, events, large areas (2026-11-02)
**Mask alignment (measured first, then fixed).**
- xBD label outlines fit the *before* image (median 0.8 px from its building edges) and not the *after* image (median 2.0-2.6 px, 90th percentile 7-9 px); the pre and post files carry identical geotransforms (`scripts/measure_alignment.py`, hold split, 188-562 tiles). The offset is local (building lean, different pass), not one shift per tile: the global shift from phase correlation is uncorrelated with it (r about -0.1) and applying it made things worse. Model masks follow the label frame; on the after image they sit a median 1.3 px (90th percentile 3.1 px) from roof edges (`scripts/measure_masks.py`).
- Outlines were traced through pixel centres and drawn on pixel edges, so every detected structure sat half a pixel up and left of its mask, with up to 1 px more from simplification. Now traced at 4x resolution (`alerts.outline`), simplified to 0.5 px, centroids and alert areas in the same convention; the stored outlines reproduce the predicted mask with IoU 0.998 (`scripts/check_outlines.py`). The report figure draws with sub-pixel precision.
- Rotated geotransforms (UTM uploads, grid turned a few degrees against north): the street-map view drew the image as an axis-aligned rectangle while the outlines followed the rotation, a mismatch of tens of metres at the corners. The map now uses a north-up copy of the image and damage map made with the same geotransform (`api/geoimage.py`, `GET /api/assessments/{id}/geo/{layer}`), with the fit error of the linear lon/lat approximation recorded (0.03 m on a 1.2 km UTM image). Layers menu: image opacity slider to compare the image with the street map.
- Not established: the absolute error of the georeferencing against the street map. OpenStreetMap outlines for the Santa Rosa tile (237 footprints) gave no clear overlap peak (IoU 0.17), so no number is claimed.

**Learned registration** (`api/registration.py`): DISK keypoints + LightGlue matching (kornia, Apache-2.0) -> RANSAC similarity (shift, rotation, zoom) -> accepted when at least 15 matches agree over enough of the image; SIFT as second method; phase correlation as last resort. Applied only when significant (0.15 degrees, 0.2% zoom or 1.5 px), then a residual phase-correlation step. Images larger than about 1.6k px are matched at full resolution in up to four 1280 px windows (a 3072 x 2048 mosaic: 2609 matches, 494 agree, 3.6 min on the contended CPU). Reported in the Before image panel and the report. On a burnt-out neighbourhood almost nothing is left to match (51 matches, 4 agree) and the app says so instead of guessing. Scenario `09_misregistered-before` (rotated 3 degrees, zoom 3%, shifted 11 m) is recovered as +3.26 degrees, zoom -2.8%, 11.2 m. `scripts/eval_registration.py` measures repeatability across tiles.

**Alert review and export** (`api/reviews.py`): per alert Confirm / Needs information / Dismiss with a note, stored next to the model output (`runs/app/reviews`); dismissed alerts leave the map and the report; alert table, review card, counts. Export: alerts as GeoJSON or CSV (with review status, notes, context flags), detected structures as GeoJSON.

**Upload management:** rename or correct type/date, delete (with results, caches, reviews); refused while processing.

**Event view** (`api/events.py`, `EventView.tsx`): all tiles of a disaster on one street map with their alerts, tiles ranked by severely damaged roof, xBD counts alongside for scoring, rank agreement. An event has 40-130 tiles at about a minute each on this server, so assessing runs as batches of 10 or 25 spread over the event.

**Large areas:** uploads up to 8192 px a side (about 4 km at 0.5 m) are processed in bands of 1024 px windows with uint8 probabilities (`UNetEngine.predict_stream`, equal to `predict_large` within quantisation), with block progress. Before-image coverage gaps use the post-only model per window.

**Priority context** (`api/context.py`): hospitals, clinics, schools, fire and police stations and main roads from OpenStreetMap (Overpass, fetched in the background, cached): facilities inside the alert, nearest hospital, facilities within 1 km, distance to a main road, flags in the alert card, report and exports; facility markers on the map. Overpass takes up to a minute and may be unreachable; alerts then show without context.

**Other:** E15 (misalignment-trained Siamese U-Net) appears in the model list when its training run has finished; loading state no longer sticks when switching between tiles, uploads and events; stress scenarios `09_misregistered-before` and `10_utm-rotated-grid` (`scripts/make_stress_set.py`).
**Tests:** `tests/test_features.py` (outline convention, north-up placement, registration, review and export, report, upload edit/delete, streaming inference, events) plus the earlier suite.

## A10 Map offset (Align)

xBD tiles carry an approximate geotransform. On Hurricane Harvey tile 5 the OpenStreetMap building outlines sat about 20 m from the roofs in the image (a 40 px window of edge matching gave 11 m east / 16 m north, the app's own measurement 14 m east / 23 m north; the two disagree by about 5 m, so a measured offset is good to a few metres, not better). The model's outlines always fit the image, so the fix moves image, outlines and alerts together on the street map.

- `api/geocal.py`: `set_offset` translates every longitude/latitude field of a stored record (absolute, reversible, kept in `scene.geo_offset_m`); `measure` draws OpenStreetMap buildings into the image grid and finds the shift onto the strongest image edges (same method as `snap`), with a sharpness score and the before/after disagreement as confidence.
- Endpoints: `GET/PUT /api/assessments/{aid}/geo-offset`, `POST .../geo-offset/measure` (slow: Overpass).
- Map view: **Align** menu (arrows with 1, 5 or 20 m steps, Measure from OpenStreetMap, Apply, Reset).
- Not automatic: the offset differs per image, so a measured suggestion needs a look by eye; the Events view still places tile frames with the file's own georeference.

## A11 Governance foundation and first controls (2026-11-02)

Documents (`governance/`): intended use and excluded uses, risk register (15 risks), roles, control matrix (34 controls, status per control), decision log, datasheet (xBD), model cards (E14, E15), approved default model.

Software controls:
- **Approved default model** (`governance/approved_model.json`, `engines.approved_default`): the default model for area alerts and uploads is no longer the best test score; it is the approved one (pinned to E14 until the switch to E15 is decided and logged). `/api/models` flags it.
- **Audit log** (`api/audit.py`): append-only JSON lines with a hash chain (`runs/app/audit/audit.jsonl`); entries for assessments, reviews and retractions, map offset changes, exports, upload deletion. `GET /api/audit`, `GET /api/audit/verify`. The interface sends the reviewer name in the `X-Reviewer` header.
- **Reviews** (`api/reviews.py`): a reviewer name is required; a reason is required to dismiss or retract; every decision is kept in a history; a confirmed alert can be retracted (hidden from the map, exports and report like a dismissed one).
- **Provenance** (`api/provenance.py`): each new assessment stores SHA-256 of the input images and of the checkpoint, thresholds, software versions.
- **Gates** (`api/gates.py`): quality flags stored with the assessment and shown in the alert panel (before-image coverage, shift-only registration, unmeasured alignment, residual, coarse imagery, position as filed or adjusted, model not the approved default).
- **Exports and report**: GeoJSON and CSV carry a draft notice, the flags, the checkpoint hash and the position offset; the report's "Method and limits" lists traceability, flags, position status and the intended-use line.
- Assessments made before this change have no provenance; the report says so. Re-run them to record it.

Evaluation script: `scripts/eval_registration_effect.py` (E15c). Registration can run on a GPU for evaluation (`REGISTRATION_DEVICE`); the app stays on the CPU.
Tests: 42 pass (7 new in `tests/test_governance.py`, which also covers the approved default); the suite never writes to the real audit log (`tests/conftest.py`).

## A12 Calibration, evidence strength per alert, retention rule (2026-11-02)
- `src/calibrate.py`: temperature scaling of the damage head on validation pairs of the training pool, ECE before and after, coverage-risk table; writes `runs/<run>/calibration.json`. The engine applies the temperature only when the file says `"apply": true` (ECE lowered by at least 0.005). For E14 the temperature is 1.05 and the head is already well calibrated at pixel level (ECE 0.056), so it is not applied.
- Each area alert now carries `low_confidence_structures` and `low_confidence_share` (members below the review confidence); shown in the alert card ("weak evidence: check first" when at least half), in the GeoJSON and in the CSV.
- Upload retention rule and notice: `governance/retention.json`, `GET /api/policy`, notice in the upload dialog; with `upload_retention_days` set, expired uploads are deleted at start-up and logged to the audit log. Default: no automatic deletion.
- `scripts/measure_offset_study.py` (X8) runs the Align measurement on 3 tiles per event of the hold split.
- Tests: 9 in `tests/test_governance.py`; the full suite has 44 tests. `test_uploads.py::test_plain_pair_with_its_own_before_corners` failed once when the server was running three other jobs and passed alone; it waits on the background worker.
