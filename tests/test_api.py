"""API routes end to end with FastAPI's TestClient (classifier B on a small hold scene, CPU)."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.api.scenes import catalogue

client = TestClient(app)


@pytest.fixture(scope="module")
def small_scene():
    df = catalogue()
    return df[(df.split == "hold") & (df.buildings.between(10, 40)) & (df.severe_true > 0)].pair_id.iloc[0]


def test_health_and_models():
    assert client.get("/api/health").json()["ok"]
    ids = [m["id"] for m in client.get("/api/models").json()]
    assert "clf_B" in ids and "clf_A" in ids


def test_scene_list_and_detail(small_scene):
    r = client.get("/api/scenes", params={"split": "hold"}).json()
    assert len(r["scenes"]) > 100 and r["disasters"]
    d = client.get(f"/api/scenes/{small_scene}").json()
    assert d["split"] == "hold" and 0.3 < d["pixel_size_m"] < 0.6
    assert client.get(f"/api/scenes/{small_scene}/image/post").headers["content-type"] == "image/jpeg"
    assert client.get("/api/scenes/nope_000/image/post").status_code == 404


def test_assess_summary_and_crop(small_scene):
    r = client.post("/api/assess", json={"pair_id": small_scene, "model_id": "clf_B", "force": True})
    assert r.status_code == 200
    aid = r.json()["id"]
    fc = client.get(f"/api/assessments/{aid}").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == fc["summary"]["buildings"]
    p = fc["features"][0]["properties"]
    assert abs(sum(p["class_probabilities"].values()) - 1) < 1e-3
    s = client.get(f"/api/assessments/{aid}/summary").json()
    assert "zones" in s and s["model"]["id"] == "clf_B"
    uid = fc["features"][0]["id"]
    assert client.get(f"/api/scenes/{small_scene}/buildings/{uid}/crop/pre").headers["content-type"] == "image/png"
    assert client.get(f"/api/assessments/{aid}/damage-map").status_code == 404  # classifiers have no pixel map
    assert client.post("/api/assess", json={"pair_id": small_scene, "model_id": "nope"}).status_code == 404
