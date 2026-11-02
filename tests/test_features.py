"""Outline geometry, north-up map images, learned/classical registration, alert review and export, upload management,
block-wise inference, events."""
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import alerts as al
from app.api import geoimage, imagery, registration, report, reviews, service, uploads
from app.api.main import app


# ---- outlines: pixel (i, j) covers [j, j + 1] x [i, i + 1] ---------------------------------------------------

def test_outline_follows_pixel_edges_not_centres():
    m = np.zeros((60, 80), bool)
    m[30:40, 20:30] = True                       # a 10 x 10 px block at x 20..30, y 30..40
    ring = al.outline(m, 0.5)
    assert abs(ring[:, 0].min() - 20) <= 0.13 and abs(ring[:, 0].max() - 30) <= 0.13
    assert abs(ring[:, 1].min() - 30) <= 0.13 and abs(ring[:, 1].max() - 40) <= 0.13


def test_structure_polygon_and_centroid_use_the_same_convention():
    loc = np.zeros((100, 100), np.uint8)
    loc[10:30, 40:60] = 1
    dmg = loc * 2
    structs, _ = al.structures(loc, dmg, np.full((4, 100, 100), 0.25, np.float32), lambda x, y: (x, y), 0.5)
    s = structs[0]
    poly = np.array(s["polygon_px"])
    assert abs((poly[:, 0].min() + poly[:, 0].max()) / 2 - s["centroid_px"][0]) < 0.2
    assert abs((poly[:, 1].min() + poly[:, 1].max()) / 2 - s["centroid_px"][1]) < 0.2
    assert abs(s["centroid_px"][0] - 50) < 0.01 and abs(s["centroid_px"][1] - 20) < 0.01      # block centre in edge coordinates


# ---- north-up copies for rotated geotransforms --------------------------------------------------------------

def test_north_up_image_lands_where_the_geotransform_says():
    th, s = np.radians(2.0), 5e-6
    gt = [-122.7, s * np.cos(th), s * np.sin(th), 38.5, s * np.sin(th) * 0.8, -s * np.cos(th) * 0.8]
    img = np.zeros((400, 400, 3), np.uint8)
    img[100:120, 200:230] = (255, 0, 0)
    assert geoimage.is_rotated(gt) and not geoimage.is_rotated([0, 1e-5, 0, 0, 0, -1e-5])
    out = cv2.imdecode(np.frombuffer(geoimage.north_up(img, gt, 0.5), np.uint8), cv2.IMREAD_UNCHANGED)
    west, north, dlon, dlat, _, _ = geoimage.grid(gt, 400, 400, 0.5)
    ys, xs = np.nonzero((out[..., 2] > 200) & (out[..., 1] < 60))
    lon, lat = west + (xs.mean() + 0.5) * dlon, north - (ys.mean() + 0.5) * dlat
    elon, elat = gt[0] + 215 * gt[1] + 110 * gt[2], gt[3] + 215 * gt[4] + 110 * gt[5]
    assert abs(lon - elon) < 0.25 * dlon and abs(lat - elat) < 0.25 * dlat
    assert out[0, 0, 3] == 0                    # outside the rotated image is transparent


# ---- registration --------------------------------------------------------------------------------------------

def textured(n=800, seed=0):
    rng = np.random.default_rng(seed)
    img = np.zeros((n, n), np.float32)
    for _ in range(900):
        x, y, r = rng.integers(0, n, 2).tolist() + [int(rng.integers(3, 14))]
        cv2.circle(img, (x, y), r, float(rng.integers(40, 255)), -1)
        cv2.rectangle(img, (x + 5, y + 5), (x + 5 + r * 2, y + 5 + r), float(rng.integers(40, 255)), -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)


@pytest.mark.parametrize("deg,scale,dx,dy", [(0, 1.0, 0, 0), (3.0, 1.0, 12, -7), (-2.0, 1.03, -20, 15)])
def test_sift_registration_recovers_rotation_zoom_shift(deg, scale, dx, dy):
    post = textured()
    n = post.shape[0]
    m = cv2.getRotationMatrix2D((n / 2, n / 2), deg, scale)
    m[:, 2] += (dx, dy)
    pre = cv2.warpAffine(post, m, (n, n), borderMode=cv2.BORDER_REFLECT)       # `pre` is `post` moved by m
    reg = registration.register(pre, post, None, methods=("sift",))
    assert reg.ok and reg.method == "sift"
    inv = cv2.invertAffineTransform(m)                                        # what registration should recover
    pts = np.float32([[0, 0], [n, 0], [n, n], [0, n]])
    est = pts @ np.float32(reg.matrix)[:, :2].T + np.float32(reg.matrix)[:, 2]
    truth = pts @ inv[:, :2].T + inv[:, 2]
    assert np.linalg.norm(est - truth, axis=1).max() < 1.5
    pre2, valid2 = registration.apply(reg, pre, np.ones((n, n), bool))
    assert valid2.mean() > 0.8


def test_large_images_are_matched_in_full_resolution_windows():
    assert registration._windows(1024, 1024) == [(0, 0, 1024, 1024)]
    assert registration._windows(1500, 1500) == [(0, 0, 1500, 1500)]            # not much above the matching size: one reduced window
    wins = registration._windows(2048, 3072)
    assert len(wins) == 4 and all(h == w == registration.MAX_SIDE for _, _, h, w in wins)
    assert {(y, x) for y, x, _, _ in wins} == {(0, 0), (0, 1792), (768, 0), (768, 1792)}      # the corners: matches spread over the image


def test_registration_rejects_unrelated_images():
    reg = registration.register(textured(seed=1), textured(seed=2), None, methods=("sift",))
    assert not reg.ok


# ---- review and export ---------------------------------------------------------------------------------------

def alert(i, sev, lon):
    ring = [[lon, 38.0], [lon + 1e-4, 38.0], [lon + 1e-4, 38.0001], [lon, 38.0001], [lon, 38.0]]
    return {"alert_id": f"AL-0000000{i}", "severity": sev, "status": "draft", "rule": "r", "severe_area_m2": 300.0 + i,
            "building_area_m2": 500.0, "severe_share": 0.6, "structures": 4, "severe": 3, "counts": {},
            "centroid_px": [10, 10], "centroid_lat": 38.00005, "centroid_lon": lon, "area_m2": 900.0, "hull_px": [[0, 0]],
            "hull_lonlat": ring, "member_ids": [], "model_id": "m", "priority": 3.0}


@pytest.fixture()
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "STORE", tmp_path / "assessments")
    monkeypatch.setattr(report, "STORE", tmp_path / "assessments")
    monkeypatch.setattr(reviews, "STORE", tmp_path / "reviews")
    (tmp_path / "assessments").mkdir()
    rec = {"id": "t_0001__m__area", "kind": "area", "pair_id": "t_0001", "created_utc": "2026-11-02 00:00:00",
           "scene": {"name": "Test event", "geotransform": [10, 1e-5, 0, 50, 0, -1e-5], "pixel_size_m": 0.5, "size_px": 1024,
                     "disaster": "Test event", "disaster_type": "fire", "pre_date": "2026-01-01", "post_date": "2026-11-01",
                     "centre_lat": 50.0, "centre_lon": 10.0},
           "model": {"label": "Test model", "mode": "pre + post", "run": "r", "epoch": 3, "checkpoint": "runs/r/best.pt", "git_commit": "not recorded"},
           "summary": {"buildings": 1, "assessed": 1, "needs_review": 0, "coverage": 1.0, "severe_assessed": 1, "severe_share": 1.0,
                       "predicted": {"destroyed": 1, "major-damage": 0, "minor-damage": 0, "no-damage": 0, "not-detected": 0},
                       "truth": {}, "vs_truth": {}}, "zones": [], "isolated_severe": [], "alerts": [alert(1, "high", 10.0), alert(2, "medium", 10.01), alert(3, "medium", 10.02)],
           "alert_rule": "rule", "features": [{"type": "Feature", "id": "S0001", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
                                               "properties": {"predicted_class": "destroyed", "confidence": 0.9, "area_m2": 12.5, "review_status": "auto"}}]}
    (tmp_path / "assessments" / f"{rec['id']}.json").write_text(json.dumps(rec))
    return rec


def test_review_lifecycle_and_export(stored):
    c, aid = TestClient(app), stored["id"]
    assert c.get(f"/api/assessments/{aid}/reviews").json()["counts"]["pending"] == 3
    r = c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", json={"reviewer": "A. Analyst", "status": "confirmed", "note": "checked with the fire brigade"})
    assert r.status_code == 200 and r.json()["counts"]["confirmed"] == 1
    c.put(f"/api/assessments/{aid}/alerts/AL-00000002/review", json={"reviewer": "A. Analyst", "status": "dismissed", "note": "parking lot"})
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000003/review", json={"reviewer": "A. Analyst", "status": "bogus"}).status_code == 400
    assert c.put(f"/api/assessments/{aid}/alerts/AL-99999999/review", json={"reviewer": "A. Analyst", "status": "confirmed"}).status_code == 404
    got = c.get(f"/api/assessments/{aid}/reviews").json()
    assert got["alerts"]["AL-00000001"]["note"].startswith("checked") and got["counts"] == {"pending": 1, "confirmed": 1, "dismissed": 1, "needs_info": 0, "retracted": 0}
    gj = c.get(f"/api/assessments/{aid}/export.geojson").json()          # dismissed left out by default
    assert [f["id"] for f in gj["features"]] == ["AL-00000001", "AL-00000003"]
    assert gj["features"][0]["properties"]["review_status"] == "confirmed" and gj["features"][0]["geometry"]["type"] == "Polygon"
    allg = c.get(f"/api/assessments/{aid}/export.geojson?include=pending,confirmed,needs_info,dismissed").json()
    assert len(allg["features"]) == 3
    only = c.get(f"/api/assessments/{aid}/export.geojson?include=confirmed").json()
    assert [f["id"] for f in only["features"]] == ["AL-00000001"]
    csv = c.get(f"/api/assessments/{aid}/export.csv").text.splitlines()
    assert csv[0].startswith("number,alert_id,severity,review_status") and len(csv) == 3 and "confirmed" in csv[1]
    st = c.get(f"/api/assessments/{aid}/export.geojson?layer=structures").json()
    assert st["features"][0]["geometry"]["coordinates"][0][1] == [10.0001, 50.0]           # x = 10 px -> lon
    # reset to untouched
    c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", json={"reviewer": "A. Analyst", "status": "pending"})
    assert c.get(f"/api/assessments/{aid}/reviews").json()["counts"]["pending"] == 2


def test_report_follows_the_review(stored):
    c, aid = TestClient(app), stored["id"]
    c.put(f"/api/assessments/{aid}/alerts/AL-00000002/review", json={"reviewer": "A. Analyst", "status": "dismissed", "note": "parking lot"})
    c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", json={"reviewer": "A. Analyst", "status": "confirmed", "note": "verified"})
    md = c.get(f"/api/assessments/{aid}/report.md").text
    assert "AL-00000002" not in md and "AL-00000001" in md and "Confirmed" in md and "verified" in md and "1 dismissed" in md
    assert "| 3 | AL-00000003" in md                         # numbers are the app's numbers, not renumbered


# ---- upload management --------------------------------------------------------------------------------------

def test_upload_rename_and_delete(tmp_path, monkeypatch, stored):
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(uploads, "REVIEWS", tmp_path / "reviews")
    uid, d = uploads.new_folder()
    (d / "meta.json").write_text(json.dumps({"id": uid, "name": "Old name", "disaster_type": "fire", "event_date": None,
                                             "created_utc": "now", "model_id": "m"}))
    (d / "status.json").write_text(json.dumps({"state": "done"}))
    rec = {**stored, "id": f"{uid}__m__area", "pair_id": uid, "scene": {**stored["scene"], "name": "Old name", "disaster": "Old name"}}
    (service.STORE / f"{rec['id']}.json").write_text(json.dumps(rec))
    (service.STORE / f"{rec['id']}_damage.png").write_bytes(b"x")
    c = TestClient(app)
    r = c.patch(f"/api/uploads/{uid}", json={"name": "  Renamed  ", "disaster_type": "flooding", "event_date": "2026-10-31"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert json.loads((service.STORE / f"{rec['id']}.json").read_text())["scene"]["name"] == "Renamed"
    assert c.patch(f"/api/uploads/{uid}", json={"disaster_type": "meteor"}).status_code == 400
    assert c.patch(f"/api/uploads/{uid}", json={"event_date": "31/10/2026"}).status_code == 400
    uploads._active.add(uid)
    assert c.delete(f"/api/uploads/{uid}").status_code == 409            # still processing
    uploads._active.discard(uid)
    assert c.delete(f"/api/uploads/{uid}").status_code == 200
    assert not d.exists() and not list(service.STORE.glob(f"{uid}*"))
    assert c.delete(f"/api/uploads/{uid}").status_code == 404
    assert c.delete("/api/uploads/not-an-id").status_code == 404


# ---- block-wise inference ------------------------------------------------------------------------------------

@pytest.mark.skipif("unet_post" not in service.models(), reason="needs the post-only U-Net checkpoint")
def test_streaming_inference_matches_whole_image_inference():
    from app.api.engines import XBD
    from app.api.scenes import catalogue
    r = catalogue().query("split == 'hold'").sort_values("severe_true").iloc[-1]
    img = cv2.cvtColor(cv2.imread(str(XBD / r.split / "images" / f"{r.pair_id}_post_disaster.png")), cv2.COLOR_BGR2RGB)
    big = np.concatenate([img[:, :640], img[:, :640]], axis=1)[:960]        # 960 x 1280 (multiples of 32): several overlapping windows
    eng = service.engine("unet_post")
    lp, dp = eng.predict_large(big, big, win=640, overlap=128)
    ls, ds = eng.predict_stream(big, big, win=640, overlap=128)
    assert ls.dtype == np.uint8 and ds.shape == (4, 960, 1280)
    assert np.abs(ls / 255 - lp).max() < 0.01 and np.abs(ds / 255 - dp).max() < 0.01


# ---- events --------------------------------------------------------------------------------------------------

@pytest.mark.skipif("unet_post" not in service.models(), reason="needs the post-only U-Net checkpoint")
def test_events_list_and_detail():
    c = TestClient(app)
    ev = c.get("/api/events?model_id=unet_post").json()
    assert ev and {"disaster", "tiles", "assessed", "alerts"} <= set(ev[0])
    resp = c.get(f"/api/events/{ev[0]['disaster']}?model_id=unet_post")
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert len(d["tiles"]) == ev[0]["tiles"] and all("pair_id" in t for t in d["tiles"])
    assert c.get("/api/events/nowhere?model_id=unet_post").status_code == 404
    assert c.get("/api/events?model_id=clf_B").status_code == 400


# ---- map offset ----------------------------------------------------------------------------------------------

def _record():
    gt = [-95.5, 4e-6, 0.0, 29.8, 0.0, -4e-6]
    return {"scene": {"geotransform": gt, "centre_lat": 29.79, "centre_lon": -95.49, "pixel_size_m": 0.44},
            "alerts": [{"centroid_lat": 29.79, "centroid_lon": -95.49, "hull_lonlat": [[-95.49, 29.79], [-95.48, 29.79]]}],
            "below_threshold": [{"centroid_lat": 29.7, "centroid_lon": -95.4}],
            "features": [{"properties": {"centroid_lnglat": [-95.49, 29.79]}}]}


def test_geo_offset_moves_everything_and_reverts():
    import copy, math
    from app.api import geocal
    rec = _record()
    orig = copy.deepcopy(rec)
    e = geocal.set_offset(rec, 11.0, 16.0, "manual")
    assert e["east"] == 11.0 and rec["scene"]["geo_offset_m"]["north"] == 16.0
    dlat = rec["alerts"][0]["centroid_lat"] - 29.79
    dlon = rec["alerts"][0]["centroid_lon"] + 95.49
    assert abs(dlat * geocal.M_PER_DEG - 16.0) < 0.01
    assert abs(dlon * geocal.M_PER_DEG * math.cos(math.radians(29.79)) - 11.0) < 0.01
    # every placement field moved by the same amount: geotransform origin, hull, feature centroid, other alerts
    assert abs((rec["scene"]["geotransform"][3] - 29.8) - dlat) < 1e-12 and abs((rec["scene"]["geotransform"][0] + 95.5) - dlon) < 1e-9
    assert abs(rec["alerts"][0]["hull_lonlat"][1][1] - 29.79 - dlat) < 1e-12
    assert abs(rec["features"][0]["properties"]["centroid_lnglat"][0] + 95.49 - dlon) < 1e-9
    assert rec["scene"]["geotransform"][1] == 4e-6                  # pixel size untouched
    # absolute, not cumulative: asking for the same offset again changes nothing; zero restores the file position
    again = copy.deepcopy(rec)
    geocal.set_offset(again, 11.0, 16.0, "manual")
    assert again["alerts"] == rec["alerts"]
    geocal.set_offset(rec, 0.0, 0.0, "manual")
    assert rec["scene"]["geo_offset_m"]["method"] is None
    assert abs(rec["scene"]["geotransform"][3] - orig["scene"]["geotransform"][3]) < 1e-8
    assert abs(rec["alerts"][0]["centroid_lon"] - orig["alerts"][0]["centroid_lon"]) < 1e-8


def test_geo_offset_limit_and_measure_recovers_shift(monkeypatch):
    import cv2
    from app.api import geocal
    with pytest.raises(ValueError):
        geocal.set_offset(_record(), 500.0, 0.0, "manual")
    # a synthetic scene: bright "roofs" on dark ground; OpenStreetMap outlines drawn 12 px east and 8 px north of them
    rng = np.random.default_rng(3)
    img = np.full((1024, 1024, 3), 40, np.uint8)
    boxes = []
    for _ in range(40):
        x, y = rng.integers(40, 940, 2); w, h = rng.integers(25, 60, 2)
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (200, 190, 180), -1)
        boxes.append((x, y, w, h))
    rec = _record()
    gt = rec["scene"]["geotransform"]
    geo = lambda px, py: {"lon": gt[0] + (px + 0.5 + 12) * gt[1], "lat": gt[3] + (py + 0.5 - 8) * gt[5]}
    ways = [[geo(x, y), geo(x + w, y), geo(x + w, y + h), geo(x, y + h)] for x, y, w, h in boxes]
    monkeypatch.setattr(geocal, "_osm_buildings", lambda *a: ways)
    s = geocal.measure(rec, lambda phase: img)
    # the outlines lie east and north of the roofs, so the image has to move 12 px east and 8 px north to meet them
    assert abs(s["east_m"] - 12 * 0.44) < 0.6 and abs(s["north_m"] - 8 * 0.44) < 0.6
    assert s["clear"]
