#!/bin/sh
# Start the damage-assessment app on 127.0.0.1:8000 (reach it from the Mac with: ssh -N -L 8000:127.0.0.1:8000 EnviroSense).
# CPU inference with 2 torch threads, so it never touches the GPUs used for training.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"  # project root (the AI repo checkout)
cd "$root"
[ -d app/web/dist ] || { echo "build the frontend first: (cd app/web && npm run build)"; exit 1; }
exec "$root/scripts/bg.sh" app env APP_TORCH_THREADS=2 CUDA_VISIBLE_DEVICES= \
    "$HOME/.local/bin/uv" run --no-sync uvicorn app.api.main:app --host 127.0.0.1 --port 8000
