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
