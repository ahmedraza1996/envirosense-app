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


# ---- audit log, review history, gates, provenance -------------------------------------------------------------

import pytest

from app.api import audit, gates, provenance, reviews


def test_audit_chain_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "PATH", tmp_path / "audit.jsonl")
    assert audit.verify()["ok"] and audit.verify()["entries"] == 0
    audit.log("assess", "A. Analyst", "aid1", model="m")
    audit.log("review", "A. Analyst", "aid1", status="confirmed")
    audit.log("export", None, "aid1", kind="alerts.csv")
    assert audit.verify() == {"ok": True, "entries": 3, "first_bad_line": None, "reason": ""}
    assert [r["actor"] for r in audit.read("aid1")] == ["A. Analyst", "A. Analyst", "unknown"]
    lines = audit.PATH.read_text().splitlines()
    audit.PATH.write_text("\n".join([lines[0], lines[1].replace("confirmed", "dismissed"), lines[2]]) + "\n")   # edit a line
    assert audit.verify()["ok"] is False and audit.verify()["first_bad_line"] == 2
    audit.PATH.write_text("\n".join([lines[0], lines[2]]) + "\n")                                                  # remove a line
    assert audit.verify()["ok"] is False


REC = {"alerts": [{"alert_id": "AL-1"}, {"alert_id": "AL-2"}]}


def test_review_needs_name_and_reason_and_keeps_history(tmp_path, monkeypatch):
    monkeypatch.setattr(reviews, "STORE", tmp_path / "reviews")
    with pytest.raises(reviews.ReviewError):
        reviews.set_review("a", REC, "AL-1", "confirmed", "ok", "")                       # no reviewer name
    with pytest.raises(reviews.ReviewError):
        reviews.set_review("a", REC, "AL-1", "dismissed", "", "R1")                       # no reason
    with pytest.raises(reviews.ReviewError):
        reviews.set_review("a", REC, "AL-1", "retracted", "wrong", "R1")                  # only a confirmed alert is retracted
    reviews.set_review("a", REC, "AL-1", "confirmed", "checked with the fire brigade", "R1")
    reviews.set_review("a", REC, "AL-1", "needs_info", "second look", "R2")
    reviews.set_review("a", REC, "AL-1", "confirmed", "verified on site", "R2")
    e = reviews.set_review("a", REC, "AL-1", "retracted", "site visit found no damage", "R3")
    assert e["status"] == "retracted" and e["reviewed_by"] == "R3"
    assert [(h["status"], h["by"]) for h in e["history"]] == [("confirmed", "R1"), ("needs_info", "R2"), ("confirmed", "R2"), ("retracted", "R3")]
    assert reviews.counts(REC, reviews.load("a"))["retracted"] == 1
    # retracted alerts leave the default export, like dismissed ones
    rec = {**_scene_rec(), "alerts": [_alert("AL-1"), _alert("AL-2")]}
    shown = reviews.alerts_geojson(rec, reviews.load("a"))["features"]
    assert [f["id"] for f in shown] == ["AL-2"]
    gj = reviews.alerts_geojson(rec, reviews.load("a"))
    assert "DRAFT" in gj["properties"]["note"] and gj["properties"]["gates"] == rec["gates"]


def _scene_rec():
    return {"id": "x", "scene": {"disaster": "d", "pair_id": "p"}, "model": {"label": "m", "id": "m"}, "created_utc": "2026-11-02 00:00:00",
            "alert_rule": "r", "gates": [{"code": "DRAFT_ONLY", "level": "info", "message": ""}],
            "provenance": {"checkpoint": {"sha256": "ab" * 32}}}


def _alert(i):
    return {"alert_id": i, "severity": "high", "hull_lonlat": [[0, 0], [1, 0], [1, 1]], "severe_area_m2": 300.0, "building_area_m2": 400.0,
            "severe_share": 0.75, "structures": 4, "severe": 3, "area_m2": 900.0, "centroid_lat": 1.0, "centroid_lon": 2.0, "priority": 5.0}


def test_gates_flag_what_the_analyst_must_know():
    scene = {"source": "upload", "pixel_size_m": 2.0,
             "before": {"kind": "archive", "coverage": 0.3, "method": "phase correlation", "corrected": False, "response": 0.01}}
    codes = {g["code"] for g in gates.evaluate(scene, "unet_a", "unet_b")}
    assert {"LOW_BEFORE_COVERAGE", "REGISTRATION_SHIFT_ONLY", "ALIGNMENT_UNMEASURED", "COARSE_IMAGERY",
            "MODEL_NOT_APPROVED_DEFAULT", "POSITION_AS_FILED", "DRAFT_ONLY"} <= codes
    clean = {"source": "upload", "pixel_size_m": 0.5, "geo_offset_m": {"east": 3.0, "north": -2.0, "method": "manual"},
             "before": {"kind": "upload", "coverage": 0.99, "method": "disk+lightglue", "corrected": True, "rms_px": 1.2}}
    ok = gates.evaluate(clean, "unet_b", "unet_b")
    assert not [g for g in ok if g["level"] == "warn"] and "POSITION_ADJUSTED" in {g["code"] for g in ok}


def test_provenance_hashes_inputs_and_checkpoint(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "best.pt").write_bytes(b"weights")
    img = tmp_path / "post.png"
    img.write_bytes(b"pixels")
    p = provenance.build({"after": img, "before": "archive: 2 tiles"}, tmp_path / "run", {"review_confidence": 0.6})
    import hashlib
    assert p["inputs"]["after"]["sha256"] == hashlib.sha256(b"pixels").hexdigest()
    assert p["inputs"]["before"] == {"source": "archive: 2 tiles"}
    assert p["checkpoint"]["sha256"] == hashlib.sha256(b"weights").hexdigest() and p["thresholds"]["review_confidence"] == 0.6
    assert p["software"]["python"]


def test_review_endpoint_requires_a_name_and_is_audited():
    from app.api import audit as _audit
    from app.api import service
    c = TestClient(app)
    # unknown assessment: 404, and nothing is logged for it
    r = c.put("/api/assessments/nope/alerts/AL-1/review", json={"status": "confirmed", "reviewer": "R1"})
    assert r.status_code == 404 and _audit.read() == []
    assert c.get("/api/audit/verify").json()["ok"] is True


def test_retention_rule_deletes_only_expired_uploads(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.api import uploads
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(uploads, "RETENTION", tmp_path / "retention.json")
    now = datetime.now(timezone.utc)
    for uid, age, state in (("upl_00000001", 40, "done"), ("upl_00000002", 5, "done"), ("upl_00000003", 40, "running")):
        d = uploads.UPLOADS / uid
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": uid, "name": uid, "created_utc": (now - timedelta(days=age)).strftime("%Y-%m-%d %H:%M:%S")}))
        (d / "status.json").write_text(json.dumps({"state": state}))
    assert uploads.expired(None) == []                                                # no rule: nothing is ever deleted
    # old uploads go; an old one marked "running" that no worker holds is an interrupted job (info() reports it as failed) and goes too
    assert set(uploads.expired(30)) == {"upl_00000001", "upl_00000003"}
    uploads.RETENTION.write_text(json.dumps({"upload_retention_days": 30, "notice": "n"}))
    assert set(uploads.purge_expired()) == {"upl_00000001", "upl_00000003"}
    assert not (uploads.UPLOADS / "upl_00000001").exists() and (uploads.UPLOADS / "upl_00000002").exists()   # the recent upload stays
    last = audit.read()[-1]
    assert last["action"] == "delete_upload" and last["actor"].startswith("system")


def test_policy_endpoint_gives_the_upload_notice():
    p = TestClient(app).get("/api/policy").json()
    assert "kept until you delete" in p["notice"] and p["upload_retention_days"] is None
