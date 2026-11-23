"""The governance modules, one test per control that names a test as its evidence (governance/controls.json): rights and quality of uploaded imagery,
abstention, the versioned alert rule, the release gate, reports behind the export right, review behaviour, monitoring floors, incidents, risks, decisions,
access reviews, two-step sign-in, and the compliance register and technical file built from all of it."""
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import exc

from app.api import (alerts, audit, auth, compliance, decisions, incident_register, input_quality, model_registry, monitoring, report, reviews, risks,
                     service, uploads)
from app.api.engines import ROOT
from app.api.main import app
from app.db import engine as dbe
from app.db import semantic

from app.tests.conftest import only_admin

c = TestClient(app)
EXC = "test models have no run records; released to test the approval workflow"


# ---- a small synthetic assessment: two damaged blocks, one sure and one unsure -------------------------------------------

def _maps(conf=0.95, size=200):
    loc = np.zeros((size, size), bool)
    loc[20:70, 20:70] = True                                     # 2,500 px = 625 m2 at 0.5 m: one alert
    prob = np.zeros((4, size, size), np.float32)
    prob[0] = (1 - conf) / 3
    prob[1] = (1 - conf) / 3
    prob[2] = (1 - conf) / 3
    prob[3] = conf                                               # destroyed
    dmg = (prob.argmax(0) + 1).astype(np.uint8) * loc
    return loc, dmg, prob


@pytest.fixture()
def synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "STORE", tmp_path / "assessments")
    monkeypatch.setattr(report, "STORE", tmp_path / "assessments")
    run = "S_r34_paired_mis"
    models = {"unet_t": {"id": "unet_t", "label": "test model", "kind": "unet", "run_dir": ROOT / "runs" / run, "test_score": 0.6}}
    monkeypatch.setattr(service, "models", lambda: models)
    semantic.sync_models({"unet_t": {"kind": "unet", "label": "test model"}})
    eng = SimpleNamespace(info={"run": run, "checkpoint": "runs/x/best.pt", "git_commit": "abc", "epoch": 1, "arch": "resnet34"},
                          mode="pre + post (Siamese)", kind="unet", temperature=1.0)

    def make(key="tile_0001", conf=0.95, abstain=None):
        loc, dmg, prob = _maps(conf)
        sc = {"pair_id": key, "source": "test", "split": "hold", "disaster": "test-fire", "disaster_type": "fire", "pixel_size_m": 0.5,
              "pre_date": "2020-01-01", "post_date": "2020-02-01", "centre_lat": 0.0, "centre_lon": 0.0, "size_px": 200}
        return service.area_record(key, sc, "unet_t", eng, loc, dmg, prob, lambda x, y: (x * 1e-5, -y * 1e-5), 0.5, abstain=abstain)
    return make


# ---- governance: decisions, technical file --------------------------------------------------------------------------------

def test_decisions_are_recorded_and_cannot_be_changed(login_as):
    decisions.record("scope", "Routing stays out of scope", "proposal section 5", "pi")
    adm = login_as("dec_admin", "admin")
    only_admin("dec_admin")
    r = c.put("/api/admin/thresholds/review_confidence", headers=adm, json={"value": 0.75, "reason": "fewer structures to review"})
    assert r.status_code == 200
    rows = decisions.list_decisions()
    assert [d["kind"] for d in rows][:2] == ["threshold", "scope"] and "0.75" in rows[0]["decision"]
    for sql in ("UPDATE gov.decisions SET reason = 'edited'", "DELETE FROM gov.decisions"):
        with pytest.raises(exc.DBAPIError, match="cannot be changed|permission denied"):
            with dbe.tx("owner") as conn:
                conn.execute(sa.text(sql))
    assert "| threshold |" in decisions.markdown()


def test_technical_file_lists_every_control():
    text = compliance.technical_file()
    for ctl in compliance.controls()["controls"]:
        assert f"| {ctl['id']} {ctl['name']} |" in text, ctl["id"]
    assert "## 4. Frameworks" in text and "EU AI Act" in text and "## 7. Decision log" in text


def test_no_pair_is_in_two_splits():
    rows = list(csv.DictReader((ROOT / "configs" / "pair_splits.csv").open()))
    seen = {}
    for r in rows:
        seen.setdefault(r["pair_id"], set()).add(r["official_split"])
    assert rows and all(len(s) == 1 for s in seen.values())
    assert compliance._leakage_free()[0] == "ok"


# ---- release gate ---------------------------------------------------------------------------------------------------------

def _run_dir(path: Path, good: bool) -> Path:
    path.mkdir(parents=True)
    (path / "best.pt").write_bytes(b"weights")
    (path / "config.json").write_text(json.dumps({"git_commit": "abc", "splits_sha256": "def", "seed": 0, "command": "train", "encoder": "resnet34"}))
    m = {"score": 0.7, "loc_f1": 0.8, "dmg_f1": 0.6, "destroyed": 0.7, "minor-damage": 0.4 if good else 0.2}
    (path / "test_metrics.json").write_text(json.dumps({"test": m, "hold": m}))
    (path / "robustness.json").write_text(json.dumps({"results": [{"condition": "as stored (xBD pairs)", "score": 0.7},
                                                                  {"condition": "shift 8 px (4 m)", "score": 0.68}, {"condition": "rotate 2 deg", "score": 0.6}]}))
    (path / "calibration.json").write_text(json.dumps({"ece_before": 0.03, "coverage_risk_after": [{"threshold": 0.7, "coverage": 0.6, "error_rate_kept": 0.05}]}))
    (path / "seeds.json").write_text(json.dumps({"hold": [0.68, 0.7, 0.69]}))
    (path / "unseen_metrics.json").write_text(json.dumps({"mean": 0.5, "events": {"a": 0.45, "b": 0.55}}))
    (path / "model_card.md").write_text("# card")
    return path


def test_release_gate_blocks_a_model_that_misses_criteria_unless_an_exception_is_given(tmp_path, monkeypatch, login_as):
    models = {"unet_good": {"kind": "unet", "label": "good", "run_dir": _run_dir(tmp_path / "good", True)},
              "unet_weak": {"kind": "unet", "label": "weak", "run_dir": _run_dir(tmp_path / "weak", False)}}
    monkeypatch.setattr(service, "models", lambda: models)
    assert model_registry.scorecard("unet_good")["gate_open"]
    weak = model_registry.scorecard("unet_weak")
    assert not weak["gate_open"] and weak["failed"] == ["AC-1e"]
    adm = login_as("gate_admin", "admin")
    only_admin("gate_admin")
    r = c.put("/api/admin/approved-model", headers=adm, json={"model_id": "unet_weak", "reason": "the minor class does not matter here"})
    assert r.status_code == 400 and "release gate is closed" in r.text and "AC-1e" in r.text
    r = c.put("/api/admin/approved-model", headers=adm, json={"model_id": "unet_weak", "reason": "field test of the weak model",
                                                              "exception": "minor damage is not used for dispatch in this field test"})
    assert r.status_code == 200 and semantic.approved_id() == "unet_weak"
    d = decisions.list_decisions()[0]
    assert d["kind"] == "model_release" and "written exception" in d["reason"] and "AC-1e" in d["reason"]
    assert c.put("/api/admin/approved-model", headers=adm, json={"model_id": "unet_good", "reason": "passes every pass mark"}).status_code == 200
    reg = {m["id"]: m for m in model_registry.registry()}
    assert reg["unet_good"]["status"] == "approved" and reg["unet_good"]["gate_open"] and not reg["unet_weak"]["gate_open"]


# ---- image intake ---------------------------------------------------------------------------------------------------------

def _jpeg(exif=True) -> bytes:
    from PIL import Image
    img = Image.fromarray((np.random.default_rng(0).random((64, 64, 3)) * 255).astype(np.uint8))
    buf = io.BytesIO()
    if exif:
        e = img.getexif()
        e[0x010F] = "PhoneMaker"                          # camera make
        e[0x0110] = "PhoneModel"
        img.save(buf, "JPEG", exif=e)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


def test_upload_needs_source_licence_and_rights(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "models", lambda: {"unet_x": {"kind": "unet"}})
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")
    got = {}
    monkeypatch.setattr(uploads, "create", lambda a, meta, b=None: got.update(meta=meta, path=a))
    monkeypatch.setattr(uploads, "info", lambda uid: {"id": uid})
    files = {"after": ("after.jpg", _jpeg(), "image/jpeg")}
    base = {"name": "x", "disaster_type": "fire", "model_id": "unet_x", "west": 1, "south": 1, "east": 1.01, "north": 1.01}
    r = c.post("/api/uploads", files=files, data=base)
    assert r.status_code == 400 and "source" in r.text
    r = c.post("/api/uploads", files=files, data={**base, "source": "Maxar open data", "licence": "CC BY-NC 4.0"})
    assert r.status_code == 400 and "right to process" in r.text
    r = c.post("/api/uploads", files=files, data={**base, "source": "Maxar open data", "licence": "CC BY-NC 4.0", "rights_confirmed": "true"})
    assert r.status_code == 200, r.text
    m = got["meta"]
    assert (m["source"], m["licence"], m["rights_confirmed_by"]) == ("Maxar open data", "CC BY-NC 4.0", "test_officer")
    assert m["privacy"]["removed"] == ["EXIF/XMP"]
    from PIL import Image
    assert not Image.open(got["path"]).getexif()                              # the saved file has no camera metadata left
    assert audit.read()[-1]["action"] == "upload" and audit.read()[-1]["detail"]["licence"] == "CC BY-NC 4.0"


def test_metadata_is_stripped_from_jpeg_and_png(tmp_path):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    j = tmp_path / "a.jpg"
    j.write_bytes(_jpeg())
    before = np.asarray(Image.open(j))
    assert input_quality.strip_metadata(j)["removed"] == ["EXIF/XMP"]
    assert not Image.open(j).getexif() and np.array_equal(np.asarray(Image.open(j)), before)       # pixels untouched: not re-encoded
    p = tmp_path / "b.png"
    info = PngInfo()
    info.add_text("Author", "someone")
    Image.fromarray(before).save(p, pnginfo=info)
    assert input_quality.strip_metadata(p)["removed"] == ["text"]
    assert not Image.open(p).text and np.array_equal(np.asarray(Image.open(p)), before)
    clean = tmp_path / "c.jpg"
    clean.write_bytes(_jpeg(exif=False))
    assert input_quality.strip_metadata(clean)["removed"] == []
    assert input_quality.strip_metadata(tmp_path / "d.tif")["kept"]


def test_unusual_and_blank_images_are_flagged(monkeypatch):
    import cv2
    rng = np.random.default_rng(1)
    grey = cv2.GaussianBlur(rng.normal(120, 40, (400, 400)).astype(np.float32), (0, 0), 1.5)
    normal = np.clip(np.stack([grey + 12, grey, grey - 12], -1), 0, 255).astype(np.uint8)
    st = input_quality.statistics(normal)
    ref = {k: [v * 0.5, v * 1.5] for k, v in st.items() if k not in ("blank_share", "cloud_share")}
    ref.update(blank_share=[0.0, 0.05], cloud_share=[0.0, 0.05])
    monkeypatch.setattr(input_quality, "reference", lambda: ref)
    ok = input_quality.assess(normal, None, 2, 0.4)
    assert ok["level"] == "ok" and not ok["unusual"]
    blank = normal.copy()
    blank[:, :250] = 0                                                       # most of the image has no data
    b = input_quality.assess(blank, None, 2, 0.4)
    assert b["level"] == "fail" and b["empty_share"] > 0.4
    cloud = np.clip(rng.normal(232, 4, (400, 400, 3)), 0, 255).astype(np.uint8)
    assert input_quality.assess(cloud, None, 2, 0.4)["stats"]["cloud_share"] > 0.9
    dark = (cv2.GaussianBlur(normal, (0, 0), 6) * 0.15).astype(np.uint8)      # dark, flat and blurred: unlike the training images
    d = input_quality.assess(dark, None, 2, 0.95)
    assert d["unusual"] and len(d["outside"]) > 2 and d["level"] == "fail"
    lines = {x["name"]: x for x in input_quality.describe(d, 2, 0.95)}
    assert lines["Unusual image"]["level"] == "fail" and "not assessed" in lines["Unusual image"]["text"]
    al = {"checks": [{"name": "Unusual image", "level": "fail", "text": "t"}, {"name": "Colour", "level": "warn", "text": "c"}]}
    assert [r["code"] for r in uploads.abstain_reasons(al)] == ["UNUSUAL_IMAGE"]


# ---- prediction and alerts --------------------------------------------------------------------------------------------------

def test_assessment_abstains_when_a_check_fails_or_most_structures_are_unsure(synthetic):
    sure = synthetic("tile_sure")
    assert not sure["abstained"] and len(sure["alerts"]) == 1
    failed = synthetic("tile_unusual", abstain=[{"code": "UNUSUAL_IMAGE", "message": "the image is unlike the training images."}])
    assert failed["abstained"] and failed["alerts"] == [] and len(failed["withheld_alerts"]) == 1
    assert failed["gates"][0]["code"] == "ABSTAINED_UNUSUAL_IMAGE"
    unsure = synthetic("tile_unsure", conf=0.4)
    assert unsure["abstained"] and [r["code"] for r in unsure["abstain_reasons"]] == ["LOW_CONFIDENCE"] and unsure["alerts"] == []
    with dbe.tx() as conn:
        got = {r["id"]: (r["abstained"], list(r["abstain_reasons"])) for r in dbe.rows(conn, "SELECT id, abstained, abstain_reasons FROM core.assessments")}
    assert got["tile_unusual__unet_t__area"] == (True, ["UNUSUAL_IMAGE"]) and got["tile_sure__unet_t__area"] == (False, [])
    assert "NOT ASSESSED" in report.markdown("tile_unsure__unet_t__area")
    assert monitoring.abstention()["abstained"] == 2


def test_alert_rule_comes_from_versioned_thresholds(synthetic):
    p = alerts.params()
    assert (p["min_severe_m2"], p["eps_m"], p["majority"]) == (250, 30, 0.5) and p["version"]
    rec = synthetic("tile_a")
    assert rec["alerts"][0]["rule_version"] == p["version"] and rec["alert_rule_version"] == p["version"]
    semantic.set_threshold("alert_min_severe_m2", 800, "t", "test")              # the 625 m2 block no longer raises an alert
    p2 = alerts.params()
    assert p2["min_severe_m2"] == 800 and p2["version"] > p["version"] and "800" in p2["text"]
    assert synthetic("tile_b")["alerts"] == []
    with pytest.raises(ValueError):
        semantic.set_threshold("alert_min_severe_m2", 5, "t", "below the lowest allowed value")


def test_thresholds_cannot_be_edited_only_added():
    semantic.set_threshold("review_confidence", 0.8, "t", "test")
    with pytest.raises(exc.DBAPIError, match="cannot be changed|permission denied"):
        with dbe.tx("owner") as conn:
            conn.execute(sa.text("UPDATE sem.thresholds SET value = 0.1 WHERE key = 'review_confidence'"))
    with pytest.raises(exc.DBAPIError, match="cannot be changed|permission denied"):
        with dbe.tx() as conn:
            conn.execute(sa.text("DELETE FROM sem.thresholds"))
    assert [h["value"] for h in semantic.threshold_history("review_confidence")][:2] == [0.8, 0.7]


# ---- human review, export ----------------------------------------------------------------------------------------------------

def _rec(n=1, aid="asm"):
    return {"id": aid, "pair_id": "p", "scene": {"disaster": "d", "pair_id": "p"}, "model": {"id": "unet_paired_mis", "label": "m"},
            "alerts": [{"alert_id": f"AL-{i}", "severity": "high", "hull_lonlat": [[0, 0], [1, 0], [1, 1]]} for i in range(1, n + 1)],
            "created_utc": "2026-11-02 00:00:00"}


def test_review_behaviour_counts_quick_confirmations():
    rec = _rec(3)
    for i, (secs, seen) in enumerate([(2.0, True), (40.0, False), (30.0, True)], 1):
        reviews.set_review("asm", rec, f"AL-{i}", "proposed", "looks right", "ana", "officer", "u")
        reviews.set_review("asm", rec, f"AL-{i}", "confirmed", "agreed", "off", "officer", "u", secs, seen)
    rb = monitoring.review_behaviour()
    assert (rb["confirmations"], rb["measured"], rb["quick"], rb["no_evidence"], rb["flagged"]) == (3, 3, 1, 1, 2)
    assert rb["by_reviewer"][0]["actor"] == "off" and rb["by_reviewer"][0]["flagged"] == 2


def test_reports_need_export_and_are_logged(synthetic, login_as):
    aid = synthetic("tile_r")["id"]
    ana = login_as("rep_analyst", "analyst")
    assert c.get(f"/api/assessments/{aid}/report.md", headers=ana).status_code == 403
    assert c.get(f"/api/assessments/{aid}/report.html", headers=ana).status_code == 403
    assert c.get(f"/api/assessments/{aid}", headers=ana).status_code == 200                      # viewing the result itself is not an export
    r = c.get(f"/api/assessments/{aid}/report.md")                                                # the test officer holds export
    assert r.status_code == 200
    exports = [e for e in audit.read() if e["action"] == "export"]
    assert exports and exports[-1]["detail"]["kind"] == "report.md" and exports[-1]["assessment"] == aid


# ---- monitoring and incidents ---------------------------------------------------------------------------------------------------

def test_live_precision_below_floor_raises_one_incident():
    semantic.set_threshold("live_precision_window", 6, "t", "test")
    rec = _rec(6)
    for i in range(1, 7):
        reviews.set_review("asm", rec, f"AL-{i}", "proposed", "ok", "ana", "officer", "u")
        if i <= 2:
            reviews.set_review("asm", rec, f"AL-{i}", "confirmed", "agreed", "off", "officer", "u")
        else:
            reviews.set_review("asm", rec, f"AL-{i}", "dismissed", "nothing there on the ground", "off", "officer", "u")
    lp = monitoring.live_precision()
    assert lp["overall"]["precision"] == pytest.approx(2 / 6, abs=1e-3) and lp["below_floor"]
    assert lp["by_model"]["unet_paired_mis"]["decided"] == 6
    monitoring.check()
    monitoring.check()                                                                         # seen again: a note, not a second incident
    found = [i for i in incident_register.list_incidents() if i["kind"] == "model_quality"]
    assert len(found) == 1 and found[0]["source"] == "check"
    assert [e["action"] for e in incident_register.get(found[0]["id"])["events"]] == ["opened", "note"]


def test_drift_raises_an_incident(make_upload):
    top = next(iter(auth.units()))
    for i in range(11):
        uid = make_upload(top, name=f"u{i}", age_days=40 if i < 5 else 1)
        with dbe.tx() as conn:
            dbe.run(conn, "UPDATE ingest.uploads SET input_quality = CAST(:q AS jsonb) WHERE id = :i",
                    q=json.dumps({"unusual": i >= 7, "empty_share": 0.1, "stats": {"brightness": 100}}), i=uid)
    d = monitoring.drift()
    assert (d["last_30_days"]["n"], d["last_30_days"]["unusual"], d["previous_30_days"]["unusual"]) == (6, 4, 0) and d["rising"]
    monitoring.check()
    assert [i["kind"] for i in incident_register.list_incidents()] == ["data_drift"]


def test_incidents_open_assess_close_and_cannot_be_deleted(login_as):
    ana = login_as("inc_analyst", "analyst")
    r = c.post("/api/gov/incidents", headers=ana, json={"kind": "wrong_alert", "severity": "serious", "title": "Alert on an empty field",
                                                        "description": "the confirmed area is a car park"})
    assert r.status_code == 200 and "supervisor within 24 hours" in r.json()["description"]
    iid = r.json()["id"]
    assert c.post(f"/api/gov/incidents/{iid}/close", headers=ana, json={"cause": "x", "resolution": "y"}).status_code == 403   # analysts raise, officers handle
    assert c.post(f"/api/gov/incidents/{iid}/assess", json={"note": "checking the imagery", "severity": "high"}).json()["state"] == "investigating"
    assert c.post(f"/api/gov/incidents/{iid}/close", json={"cause": "shadow", "resolution": "short"}).status_code == 400
    done = c.post(f"/api/gov/incidents/{iid}/close", json={"cause": "shadows read as rubble", "resolution": "alert retracted, model check scheduled"})
    assert done.json()["state"] == "closed" and done.json()["severity"] == "high"
    assert c.post(f"/api/gov/incidents/{iid}/close", json={"cause": "again", "resolution": "closing it twice"}).status_code == 409
    with pytest.raises(exc.DBAPIError, match="cannot be deleted|permission denied"):
        with dbe.tx() as conn:
            conn.execute(sa.text("DELETE FROM gov.incidents"))
    assert c.post(f"/api/gov/incidents/{iid}/reopen", json={"note": "same area flagged again"}).json()["state"] == "open"
    assert [e["action"] for e in c.get(f"/api/gov/incidents/{iid}", headers=ana).json()["events"]] == ["opened", "assessed", "closed", "reopened"]


def test_retraction_raises_an_incident(synthetic, login_as):
    aid = synthetic("tile_x")["id"]
    al = json.loads((service.STORE / f"{aid}.json").read_text())["alerts"][0]["alert_id"]
    ana, off2 = login_as("ret_analyst", "analyst"), login_as("ret_officer", "officer")
    put = lambda h, status, note: c.put(f"/api/assessments/{aid}/alerts/{al}/review", headers=h, json={"status": status, "note": note, "seconds": 20,
                                                                                                         "evidence_viewed": True})
    assert put(ana, "proposed", "visible rubble").status_code == 200
    assert put(off2, "confirmed", "agreed").status_code == 200
    assert put(off2, "retracted", "field team found the roof intact").status_code == 200
    inc = incident_register.list_incidents()
    assert len(inc) == 1 and inc[0]["kind"] == "wrong_alert" and inc[0]["links"] == {"assessment": aid, "alert_id": al}


# ---- risks, access, two-step sign-in ------------------------------------------------------------------------------------------

def test_risk_register_edits_need_a_reason_and_are_logged(login_as):
    assert len(risks.list_risks()) >= 15
    adm = login_as("risk_admin", "admin")
    assert c.put("/api/gov/risks/R01", headers=adm, json={"likelihood": 2, "reason": "short"}).status_code == 400
    r = c.put("/api/gov/risks/R01", headers=adm, json={"likelihood": 2, "controls": ["P1", "H4"], "reason": "abstention lowers the chance of a missed area"})
    assert r.status_code == 200 and r.json()["score"] == 2 * r.json()["severity"] and r.json()["controls"] == ["P1", "H4"]
    assert c.put("/api/gov/risks/R01", headers=login_as("risk_officer", "officer"), json={"likelihood": 1, "reason": "an officer may not"}).status_code == 403
    last = [e for e in audit.read() if e["action"] == "risk_change"][-1]
    assert last["actor"] == "risk_admin" and last["detail"]["after"]["likelihood"] == 2 and last["detail"]["before"]["likelihood"] == 3
    risks.update("R01", {"likelihood": 3}, "t", "restore the seeded value for other tests")


def test_access_review_cannot_review_yourself_and_disable_ends_access(login_as):
    adm = login_as("acc_admin", "admin")
    ana = login_as("acc_analyst", "analyst")
    assert c.post("/api/gov/access-reviews", headers=adm, json={"username": "acc_admin", "decision": "keep"}).status_code == 400
    assert c.post("/api/gov/access-reviews", headers=adm, json={"username": "acc_analyst", "decision": "keep"}).status_code == 200
    rows = {r["username"]: r for r in c.get("/api/gov/access-reviews", headers=adm).json()}
    assert not rows["acc_analyst"]["due"] and rows["acc_admin"]["due"]
    assert c.post("/api/gov/access-reviews", headers=adm, json={"username": "acc_analyst", "decision": "disable", "note": "left the unit"}).status_code == 200
    assert c.get("/api/auth/me", headers=ana).status_code == 401 and not auth.get_user("acc_analyst")["active"]
    with pytest.raises(exc.DBAPIError, match="cannot be changed|permission denied"):
        with dbe.tx() as conn:
            conn.execute(sa.text("DELETE FROM gov.access_reviews"))


def test_two_step_sign_in(login_as):
    h = login_as("two_step_admin", "admin")
    me = c.get("/api/auth/me", headers=h).json()
    assert me["two_step_expected"] and not me["two_step"]
    secret = c.post("/api/auth/two-step/setup", headers=h).json()["secret"]
    assert c.post("/api/auth/two-step/enable", headers=h, json={"code": "000000" if auth.totp_code(secret) != "000000" else "111111"}).status_code == 400
    assert c.post("/api/auth/two-step/enable", headers=h, json={"code": auth.totp_code(secret)}).json()["two_step"]
    body = {"username": "two_step_admin", "password": "Passw0rd-long-1"}
    fresh = TestClient(app)                                                       # its own cookie jar: signing in sets a session cookie
    r = fresh.post("/api/auth/login", json=body, headers={"Authorization": "none"})
    assert r.status_code == 401 and r.json()["detail"]["two_step"]
    wrong = "000000" if auth.totp_code(secret) != "000000" else "111111"
    assert fresh.post("/api/auth/login", json={**body, "code": wrong}, headers={"Authorization": "none"}).status_code == 401
    assert fresh.post("/api/auth/login", json={**body, "code": auth.totp_code(secret)}, headers={"Authorization": "none"}).status_code == 200
    assert compliance._two_step_coverage()[0] == "fail"                          # the test officer has not switched it on
    other = login_as("two_step_other_admin", "admin")                             # lost phone: an administrator's password reset clears two-step
    temp = c.post("/api/admin/users/two_step_admin/reset-password", headers=other).json()["temporary_password"]
    assert TestClient(app).post("/api/auth/login", json={"username": "two_step_admin", "password": temp}, headers={"Authorization": "none"}).status_code == 200
    assert [e for e in audit.read() if e["action"] == "password_reset"][-1]["detail"]["two_step_cleared"] is True


# ---- the compliance register --------------------------------------------------------------------------------------------------

def test_compliance_register_checks_every_control_and_scores_every_framework(login_as):
    r = c.get("/api/gov/controls", headers=login_as("comp_auditor", "auditor"))
    assert r.status_code == 200, r.text
    reg = r.json()
    assert len(reg["controls"]) == len(compliance.controls()["controls"])
    by = {x["id"]: x for x in reg["controls"]}
    assert by["A2"]["evidence"][2]["status"] == "ok"                              # every threshold has a stored value
    assert by["F3"]["evidence"][1]["status"] == "ok"                              # the audit chain verifies
    assert by["G8"]["status"] == "not met" and by["G8"]["evidence"][0]["detail"] == "never done"
    assert {f["key"] for f in reg["frameworks"]} == {"eu", "nist", "iso", "oecd", "data", "pk"}
    assert all(r["controls"] for f in reg["frameworks"] for r in f["requirements"])
    assert c.get("/api/gov/controls", headers=login_as("comp_analyst", "analyst")).status_code == 403
