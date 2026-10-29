# envirosense-app

Damage-assessment web app for the xBD capstone: pick a disaster tile, run a damage model, see damage on the map,
inspect buildings, and get summary counts and priority areas.

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

## Run
```sh
app/scripts/setup_node.sh                      # once: Node 22 in .cache/node
(cd app/web && npm install && npm run build)   # frontend build
app/scripts/app.sh                             # server on 127.0.0.1:8000 (CPU only)
uv run python -m pytest app/tests -q           # tests, from the project root
```
From a laptop: `ssh -N -L 127.0.0.1:8765:127.0.0.1:8000 EnviroSense`, then open http://127.0.0.1:8765 (local port 8765 avoids clashes with other services on 8000).
