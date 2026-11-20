# envirosense-app

Damage-assessment web app for the xBD capstone: pick a disaster tile or upload before/after imagery, run a damage model,
see damage on the image and on the street map, raise area alerts, review and export them, and rank the tiles of a disaster.

- **Uploads:** GeoTIFF or PNG/JPEG with corner coordinates, before image uploaded or found in an archive, learned registration
  (shift, rotation, zoom), images up to 8192 px a side processed in blocks, rename/delete.
- **Alerts:** area alerts from severely damaged roof, analyst review (confirm / needs information / dismiss, notes), GeoJSON and CSV export,
  situation report, facilities and roads from OpenStreetMap around each alert.
- **Maps:** image view and street-map view with outlines on pixel edges, north-up images for rotated grids, image opacity slider.
- **Events:** all tiles of a disaster on one map, ranked.
- **Governance:** `governance/` documents (intended use, risk register, control matrix, decision log, datasheet, model cards); approved default model; hash-chained audit log; named reviewers with history, reasons and retraction; provenance and quality flags on every new assessment.

- `api/`: FastAPI backend. Engines reuse the training code, so the app runs exactly the evaluated models
  (parity tests in `tests/`).
- `web/`: React + TypeScript + Vite + Leaflet frontend, built to `web/dist/` and served by the backend.
- `scripts/`: start the server, pre-compute demo tiles, user-space Node setup.
- `docs/app_log.md`: change log of the app.

## Layout requirement
This repo is checked out at `app/` inside the **envirosense-ai** repo (which ignores `app/`). The app reads the
training code (`src/`), data (`data/`) and checkpoints (`runs/`) from that parent checkout:

```
envirosense/            <- envirosense-ai
  src/ data/ runs/ ...
  app/                  <- envirosense-app (this repo)
```

## Run it on your own machine (macOS or Linux)
You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) running, and the **envirosense-ai** checkout set up as in its README
(`uv sync` and `sh scripts/get_models.sh`). Then, from the project root (`envirosense/`):

```sh
sh app/scripts/db_docker.sh                                   # 1. database in Docker; writes the connection strings to .env.db
(cd app && uv run alembic -c alembic.ini upgrade head)        # 2. create the tables
sh app/scripts/setup_node.sh                                  # 3. Node 22 inside the project (once)
(cd app/web && PATH="../../.cache/node/bin:$PATH" npm ci && PATH="../../.cache/node/bin:$PATH" npm run build)   # 4. build the web pages
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000  # 5. start
```
Open http://127.0.0.1:8000 and pick one of the demo accounts on the sign-in page (password `abc12345`; see `docs/operations.md`).
Uploads work with any before/after pair, for example the folders in `demo_set/`. The **Events** page also needs the xBD dataset in `data/`.

Next time only step 5 is needed (Docker Desktop must be running). Tests: `uv run python -m pytest app/tests -q`.

**Before any real use:** start with `ENVIROSENSE_DEMO_ACCOUNTS=0` so the shared demo password is switched off.

## On the project server
```sh
app/scripts/app.sh                             # server on 127.0.0.1:8000 in the background (CPU only, GPUs stay free for training)
```
From a laptop: `ssh -N -L 127.0.0.1:8765:127.0.0.1:8000 EnviroSense`, then open http://127.0.0.1:8765 (local port 8765 avoids clashes with other services on 8000).
