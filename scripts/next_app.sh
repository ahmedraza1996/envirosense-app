#!/bin/sh
# After the E12 chain (training + test + experiment records) finishes: pre-compute demo scenes, then start the app.
set -u
cd "$HOME/envirosense"
while kill -0 "$(cat runs/logs/chain_early.pid)" 2>/dev/null; do sleep 60; done
echo "E12 chain finished $(date -u)"
"$HOME/.local/bin/uv" run --no-sync python app/scripts/precompute_demo.py --per-disaster 2
echo "pre-compute finished $(date -u)"
./app/scripts/app.sh
