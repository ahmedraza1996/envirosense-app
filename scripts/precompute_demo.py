"""Pre-assess a set of hold scenes for each model so the demo is instant (results cached in runs/app/assessments).

Picks the most damaged scenes per disaster (up to --per-disaster each). CPU only, 2 torch threads.
  uv run python app/scripts/precompute_demo.py [--models clf_B unet_post] [--per-disaster 2]
"""
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("APP_TORCH_THREADS", "2")
os.environ["CUDA_VISIBLE_DEVICES"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.api import service  # noqa: E402
from app.api.scenes import catalogue  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--models", nargs="+", default=None)
p.add_argument("--per-disaster", type=int, default=2)
a = p.parse_args()
df = catalogue()
df = df[(df.split == "hold") & (df.buildings >= 10)]
picks = df.sort_values("severe_true", ascending=False).groupby("disaster").head(a.per_disaster).pair_id.tolist()
models = a.models or list(service.models())
print(f"{len(picks)} scenes x {len(models)} models: {models}", flush=True)
for m in models:
    for pid in picks:
        t = time.time()
        rec = service.assess(pid, m)
        print(f"{m} {pid} {rec[summary][buildings]} buildings {time.time() - t:.1f}s", flush=True)
