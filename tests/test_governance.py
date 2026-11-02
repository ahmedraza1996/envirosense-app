"""Governance controls that can be tested without a GPU: the approved default model."""
import json

from fastapi.testclient import TestClient

from app.api import engines
from app.api.main import app


def test_default_model_is_the_approved_one(tmp_path, monkeypatch):
    models = {"unet_a": {}, "unet_b": {}}
    f = tmp_path / "approved_model.json"
    monkeypatch.setattr(engines, "APPROVED", f)
    assert engines.approved_default(models) is None                       # no approval file: no silent default
    f.write_text(json.dumps({"default_model": "unet_b"}))
    assert engines.approved_default(models) == "unet_b"
    f.write_text(json.dumps({"default_model": "unet_missing"}))
    assert engines.approved_default(models) is None                       # approved model not available
    f.write_text("not json")
    assert engines.approved_default(models) is None


def test_models_endpoint_marks_exactly_one_approved_default():
    models = TestClient(app).get("/api/models").json()
    flagged = [m["id"] for m in models if m["approved_default"]]
    approved = json.loads(engines.APPROVED.read_text())["default_model"]
    assert flagged == [approved]
