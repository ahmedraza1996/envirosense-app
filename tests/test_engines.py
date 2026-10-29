"""Parity: the app engines must reproduce the evaluation runs exactly.

Classifier: per-building probabilities equal the saved hold-split predictions of the training run.
Run from the project root:  uv run python -m pytest app/tests -q
"""
import numpy as np
import pandas as pd
import pytest

from app.api.engines import ROOT, ClassifierEngine

SCENES_PER_MODEL = 3


@pytest.mark.parametrize("run", ["B_r18_official", "A_r18_official"])
def test_classifier_matches_reported_predictions(run):
    idx = pd.read_parquet(ROOT / "data/xbd_crops/index.parquet", columns=["row", "pair_id", "uid"])
    pred = pd.read_parquet(ROOT / f"runs/{run}/test_predictions.parquet").merge(idx, on="row")
    sizes = pred.groupby("pair_id").size().sort_values()
    scenes = sizes[(sizes >= 20) & (sizes <= 120)].index[:SCENES_PER_MODEL]  # modest scenes keep CPU time low
    engine = ClassifierEngine(ROOT / "runs" / run)
    checked = 0
    for pid in scenes:
        got = {b["uid"]: np.array(b["probs"]) for b in engine.assess("hold", pid)["buildings"]}
        for r in pred[pred.pair_id == pid].itertuples():
            expected = np.array([r.p0, r.p1, r.p2, r.p3])
            assert got[r.uid].argmax() == expected.argmax(), (pid, r.uid)
            assert np.abs(got[r.uid] - expected).max() < 1e-3, (pid, r.uid, got[r.uid], expected)
            checked += 1
    assert checked > 50
