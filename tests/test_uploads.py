"""Upload workflow: an xBD after tile uploaded like a user's image must give the same result as the benchmark tile;
the archive must find the matching before image; a georeferencing offset must be measured and corrected."""
import shutil
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.transform import Affine

from app.api import imagery, report, service, uploads
from app.api.archive import xbd_archive
from app.api.engines import XBD
from app.api.main import app
from app.api.scenes import catalogue, geotransforms

pytestmark = pytest.mark.skipif("unet_post" not in service.models(), reason="needs the post-only U-Net checkpoint")


@pytest.fixture(scope="module")
def tile():
    df = catalogue()
    r = df[(df.split == "hold") & (df.disaster == "santa-rosa-wildfire")].sort_values("severe_true").iloc[-1]
    rgb = cv2.cvtColor(cv2.imread(str(XBD / r.split / "images" / f"{r.pair_id}_post_disaster.png")), cv2.COLOR_BGR2RGB)
    return r.pair_id, rgb, Affine.from_gdal(*geotransforms()[f"{r.pair_id}_post_disaster.png"][0])


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(service, "STORE", tmp_path / "assessments")
    monkeypatch.setattr(report, "STORE", tmp_path / "assessments")
    return tmp_path


def upload(tmp_path, name, rgb, tf, model_id, **meta):
    uid, d = uploads.new_folder()
    imagery.write_geotiff(d / "after_input.tif", rgb, tf)
    (d / "meta.json").write_text(__import__("json").dumps({"id": uid, "name": name, "disaster_type": "fire",
                                                          "model_id": model_id, "after_file": "after_input.tif",
                                                          "created_utc": "now", **meta}))
    return uid, uploads.process(uid)


def test_tiled_inference_matches_tile(tile):
    pid, rgb, _ = tile
    eng = service.engine("unet_post")
    loc, dmg, _, _ = eng.predict_maps("hold", pid)
    loc_p, dmg_p = eng.predict_large(rgb, rgb)
    assert ((loc_p > 0.5) == loc).mean() > 0.9999


def test_archive_finds_the_before_image(tile):
    pid, rgb, tf = tile
    g = imagery.GeoImage(rgb, imagery.WGS84, tf)
    found = xbd_archive().search(imagery.footprint_lonlat(g))
    assert found[0]["tile"] == pid and found[0]["overlap"] > 0.95


def test_geotiff_upload_matches_benchmark(tile, store):
    pid, rgb, tf = tile
    _, rec = upload(store, "Santa Rosa sample", rgb, tf, "unet_post")
    bench = service.assess_area(pid, "unet_post", force=True)
    assert rec["scene"]["before"]["tiles"][0]["tile"] == pid
    assert rec["scene"]["before"]["coverage"] > 0.99
    assert len(rec["alerts"]) == len(bench["alerts"])
    assert rec["summary"]["predicted"] == bench["summary"]["predicted"]
    a, b = rec["alerts"][0], bench["alerts"][0]
    # areas agree to 0.1%: benchmark tiles take the metres-per-pixel at the tile's top edge, uploads at the image centre
    assert abs(a["centroid_lat"] - b["centroid_lat"]) < 1e-6 and abs(a["severe_area_m2"] / b["severe_area_m2"] - 1) < 1e-3


def test_offset_is_measured_and_corrected(tile, store):
    """xBD pairs are themselves a few pixels misregistered, so the injected 8 px offset is checked against that
    baseline: shifting the after image's georeferencing 8 px east moves the measured shift by -8 px in x."""
    pid, rgb, tf = tile
    _, base = upload(store, "Baseline", rgb, tf, "unet_post")
    _, rec = upload(store, "Offset sample", rgb, tf @ Affine.translation(8, 0), "unet_post")
    b, qa = base["scene"]["before"], rec["scene"]["before"]
    assert qa["corrected"]
    assert abs(qa["shift_px"][0] - b["shift_px"][0] + 8) < 0.5 and abs(qa["shift_px"][1] - b["shift_px"][1]) < 0.5


def test_api_plain_image_with_corners(tile, store):
    pid, rgb, tf = tile
    client = TestClient(app)
    ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    files = {"after": ("after.jpg", jpg.tobytes(), "image/jpeg")}
    r = client.post("/api/uploads", files=files, data={"name": "x", "disaster_type": "fire", "model_id": "unet_post"})
    assert r.status_code == 400 and "corner" in r.text
    gt = tf.to_gdal()
    corners = {"west": gt[0], "north": gt[3], "east": gt[0] + 1024 * gt[1], "south": gt[3] + 1024 * gt[5]}
    r = client.post("/api/uploads", files=files, data={"name": "Plain JPEG", "disaster_type": "fire",
                                                       "model_id": "unet_post", **corners})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    for _ in range(300):
        st = client.get(f"/api/uploads/{uid}").json()["status"]
        if st["state"] in ("done", "failed"):
            break
        time.sleep(1)
    assert st["state"] == "done", st
    aid = st["assessment_id"]
    rec = client.get(f"/api/assessments/{aid}").json()
    assert rec["scene"]["source"] == "upload" and rec["scene"]["width_px"] == 1024
    # JPEG compression must not break the alignment check (it did before images were smoothed for phase correlation)
    assert rec["scene"]["before"]["shift_m"] is not None and rec["scene"]["before"]["shift_m"] < 5
    assert client.get(f"/api/scenes/{uid}/image/pre").status_code == 200
    assert client.get(f"/api/assessments/{aid}/report.md").status_code == 200
    if rec["features"]:
        assert client.get(f"/api/assessments/{aid}/features/{rec['features'][0]['id']}/crop/post").status_code == 200
    assert any(u["id"] == uid for u in client.get("/api/uploads").json())
