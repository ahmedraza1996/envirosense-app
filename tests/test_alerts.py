"""Area alerts on synthetic maps: nearby damage joins one alert, distant damage is separate, small damage stays below
the threshold, and severity follows the share of severely damaged building area."""
import numpy as np

from app.api import alerts as al

PX = 0.5                                   # metres per pixel
GT = [10.0, 1e-5, 0.0, 50.0, 0.0, -1e-5]   # simple north-up geotransform


def roof(loc, dmg, x, y, size, cls):
    loc[y:y + size, x:x + size] = 1
    dmg[y:y + size, x:x + size] = cls


def run(loc, dmg):
    structs, _ = al.structures(loc, dmg, np.full((4, *loc.shape), 0.25, np.float32), al.gdal_lonlat(GT), PX)
    return al.area_alerts(loc, dmg, structs, "test_0001", al.gdal_lonlat(GT), PX, "unet_test")


def test_grouping_threshold_and_severity():
    loc = np.zeros((1024, 1024), np.uint8)
    dmg = np.zeros((1024, 1024), np.uint8)
    # area A: three destroyed 20 m roofs 10 m apart (one area), plus one intact roof -> high (most area severe)
    for x in (100, 160, 220):
        roof(loc, dmg, x, 100, 40, 4)
    roof(loc, dmg, 280, 100, 40, 1)
    # area B, 300 m away: two major roofs next to a large intact building -> medium. Only building area inside the
    # damage area (within EPS_M / 2 of severe damage) counts, so the intact block sits right beside the damage.
    for x in (100, 150):
        roof(loc, dmg, x, 700, 40, 3)
    loc[742:842, 60:260] = 1
    dmg[742:842, 60:260] = 1
    # area C: one small destroyed shed, far from everything -> below the 250 m2 threshold
    roof(loc, dmg, 900, 400, 10, 4)
    alerts, below = run(loc, dmg)
    assert len(alerts) == 2 and len(below) == 1
    high, medium = alerts
    assert high["severity"] == "high" and high["centroid_px"][1] < 200
    assert medium["severity"] == "medium" and medium["centroid_px"][1] > 600
    assert abs(high["severe_area_m2"] - 3 * (40 * PX) ** 2) < 1e-6
    assert high["alert_id"].startswith("AL-") and high["alert_id"] != medium["alert_id"]
    lon, lat = high["centroid_lon"], high["centroid_lat"]
    assert 10.0 < lon < 10.01 and 49.99 < lat < 50.0


def test_alert_ids_are_stable():
    loc = np.zeros((1024, 1024), np.uint8)
    dmg = np.zeros((1024, 1024), np.uint8)
    for x in (100, 160, 220):
        roof(loc, dmg, x, 100, 40, 4)
    assert run(loc, dmg)[0][0]["alert_id"] == run(loc, dmg)[0][0]["alert_id"]
