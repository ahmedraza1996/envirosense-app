"""Sign-in, roles, organisation scope, four-eyes confirmation, administration and the approved-model change (controls A1-A6)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.api import audit, auth, engines, reviews, service, uploads
from app.api.main import app
from app.tests.test_features import stored  # noqa: F401  (fixture: a stored area assessment with three alerts)

c = TestClient(app)


@pytest.fixture()
def tree():
    """National > Sindh > Karachi, and National > Punjab."""
    top = next(iter(auth.units()))
    sindh = auth.create_unit("Sindh PDMA", top, "t")["id"]
    karachi = auth.create_unit("Karachi district team", sindh, "t")["id"]
    punjab = auth.create_unit("Punjab PDMA", top, "t")["id"]
    return {"top": top, "sindh": sindh, "karachi": karachi, "punjab": punjab}


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def mk(username, role, unit):
    auth.create_user(username, username, role, unit, "Passw0rd-long-1", "t", must_change=False)
    return hdr(auth.make_token(username))


def test_sign_in_is_required_and_every_route_has_a_rule():
    anon = {"Authorization": "Bearer nonsense"}
    assert c.get("/api/health", headers=anon).status_code == 200
    for path in ("/api/models", "/api/scenes", "/api/uploads", "/api/audit", "/api/policy", "/api/admin/users"):
        assert c.get(path, headers=anon).status_code == 401, path
    assert TestClient(app).get("/api/models", headers={"Authorization": ""}).status_code == 401
    missing = [(m, r.path) for r in app.routes if getattr(r, "path", "").startswith("/api") for m in r.methods - {"HEAD", "OPTIONS"}
               if auth.required(m, r.path.replace("{", "x").replace("}", "")) is None]
    assert missing == []                                                          # deny by default: no route without a rule


def test_login_logout_lockout_and_password_rules():
    pw = "Right-pass-12"
    auth.create_user("kim", "Kim", "analyst", next(iter(auth.units())), pw, "t", must_change=False)
    r = TestClient(app).post("/api/auth/login", json={"username": "KIM", "password": pw}, headers={"Authorization": "x"})
    assert r.status_code == 200 and r.json()["role"] == "analyst" and "es_session" in r.cookies
    cl = TestClient(app)
    cl.cookies.set("es_session", r.cookies["es_session"])
    assert cl.get("/api/auth/me", headers={"Authorization": "x"}).json()["username"] == "kim"
    for _ in range(auth.LOCK_AFTER):
        assert TestClient(app).post("/api/auth/login", json={"username": "kim", "password": "wrong"}).status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "kim", "password": pw}).status_code == 429       # locked, even with the right password
    assert [e["action"] for e in audit.read()].count("login_failed") == auth.LOCK_AFTER + 1
    with pytest.raises(auth.AuthError):
        auth.create_user("lee", "Lee", "analyst", next(iter(auth.units())), "short", "t")
    assert "scrypt" in auth.users()["kim"]["pw"] and pw not in json.dumps(auth.users())


def test_temporary_password_must_be_changed_and_old_sessions_end():
    top = next(iter(auth.units()))
    auth.create_user("new_hire", "New Hire", "analyst", top, "Temp-pass-123", "t")                       # must_change defaults to True
    tok = auth.make_token("new_hire")
    assert c.get("/api/models", headers=hdr(tok)).status_code == 403
    assert c.get("/api/auth/me", headers=hdr(tok)).json()["must_change_password"] is True
    assert c.post("/api/auth/password", headers=hdr(tok), json={"current": "Temp-pass-123", "new": "Temp-pass-123"}).status_code == 400
    assert c.post("/api/auth/password", headers=hdr(tok), json={"current": "Temp-pass-123", "new": "A-better-pass-9"}).status_code == 200
    c.cookies.clear()                                                                                      # the browser would hold the new session cookie
    assert c.get("/api/models", headers=hdr(tok)).status_code == 401                                      # the old token no longer works
    assert auth.login("new_hire", "A-better-pass-9")[0]["must_change_password"] is False


def test_roles_limit_what_each_user_can_do(stored, tree):  # noqa: F811
    aid = stored["id"]
    ana, off, aud, adm = mk("ana", "analyst", tree["top"]), mk("off", "officer", tree["top"]), mk("aud", "auditor", tree["top"]), mk("adm", "admin", tree["top"])
    # analyst: works, but cannot export, confirm or retract
    assert c.get(f"/api/assessments/{aid}/export.csv", headers=ana).status_code == 403
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", headers=ana, json={"status": "confirmed", "note": "x"}).status_code == 403
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", headers=ana, json={"status": "proposed"}).status_code == 200
    # officer: cannot confirm their own proposal, can confirm someone else's, exports, retracts
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", headers=off, json={"status": "confirmed"}).status_code == 200
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000002/review", headers=off, json={"status": "proposed"}).status_code == 200
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000002/review", headers=off, json={"status": "confirmed"}).status_code == 400
    assert c.get(f"/api/assessments/{aid}/export.csv", headers=off).status_code == 200
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000001/review", headers=off, json={"status": "retracted", "note": "wrong"}).status_code == 200
    # auditor: reads decisions and the audit log; no alert lists, exports, imagery or decisions
    assert c.get(f"/api/assessments/{aid}/reviews", headers=aud).status_code == 200
    assert c.get("/api/audit", headers=aud).status_code == 200 and c.get("/api/audit/verify", headers=aud).json()["ok"]
    assert c.get(f"/api/assessments/{aid}/export.csv", headers=aud).status_code == 403
    assert c.get("/api/scenes", headers=aud).status_code == 403
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000003/review", headers=aud, json={"status": "needs_info"}).status_code == 403
    # administrator: manages accounts and the audit log, never imagery or alerts
    assert c.get("/api/admin/users", headers=adm).status_code == 200 and c.get("/api/audit", headers=adm).status_code == 200
    assert c.get("/api/scenes", headers=adm).status_code == 403
    assert c.put(f"/api/assessments/{aid}/alerts/AL-00000003/review", headers=adm, json={"status": "needs_info"}).status_code == 403
    assert c.get("/api/admin/users", headers=ana).status_code == 403
    denied = [e for e in audit.read() if e["action"] == "denied"]
    assert {e["actor"] for e in denied} >= {"ana", "aud", "adm"}


def test_uploads_are_visible_only_inside_the_owner_unit_tree(tmp_path, monkeypatch, tree):
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")
    ids = {}
    for who, unit in (("karachi_user", tree["karachi"]), ("punjab_user", tree["punjab"])):
        uid, d = uploads.new_folder()
        (d / "meta.json").write_text(json.dumps({"id": uid, "name": who, "created_utc": "2026-11-02 00:00:00", "model_id": "m"}))
        (d / "status.json").write_text(json.dumps({"state": "done"}))
        auth.adopt(uid, unit, who)
        ids[who] = uid
    kar, pun = mk("kar_analyst", "analyst", tree["karachi"]), mk("pun_officer", "officer", tree["punjab"])
    sindh_off, top_off = mk("sindh_officer", "officer", tree["sindh"]), mk("top_officer", "officer", tree["top"])
    names = lambda h: sorted(u["name"] for u in c.get("/api/uploads", headers=h).json())
    assert names(kar) == ["karachi_user"] and names(pun) == ["punjab_user"]               # siblings do not see each other
    assert names(sindh_off) == ["karachi_user"]                                           # seniors see the units below them
    assert names(top_off) == ["karachi_user", "punjab_user"]
    assert c.get(f"/api/uploads/{ids['punjab_user']}", headers=kar).status_code == 404
    assert c.get(f"/api/assessments/{ids['punjab_user']}__m__area/summary", headers=kar).status_code == 404
    assert c.delete(f"/api/uploads/{ids['punjab_user']}", headers=sindh_off).status_code == 404
    # an analyst deletes only their own upload; an officer above can delete any in the tree
    assert c.delete(f"/api/uploads/{ids['karachi_user']}", headers=kar).status_code == 403
    assert c.delete(f"/api/uploads/{ids['karachi_user']}", headers=sindh_off).status_code == 200


def test_administrators_manage_only_their_own_unit_tree(tree):
    sindh_admin = mk("sindh_admin", "admin", tree["sindh"])
    r = c.post("/api/admin/users", headers=sindh_admin, json={"username": "kar_new", "name": "Kar New", "role": "analyst", "unit": tree["karachi"]})
    assert r.status_code == 200 and len(r.json()["temporary_password"]) >= auth.MIN_PASSWORD and r.json()["must_change_password"]
    assert c.post("/api/admin/users", headers=sindh_admin, json={"username": "pun_new", "name": "P", "role": "analyst", "unit": tree["punjab"]}).status_code == 403
    assert c.post("/api/admin/users", headers=sindh_admin, json={"username": "x", "name": "P", "role": "analyst", "unit": tree["karachi"]}).status_code == 400
    assert c.post("/api/admin/users", headers=sindh_admin, json={"username": "bad_role", "name": "P", "role": "god", "unit": tree["karachi"]}).status_code == 400
    assert sorted(u["username"] for u in c.get("/api/admin/users", headers=sindh_admin).json()) == ["kar_new", "sindh_admin"]
    assert c.get("/api/admin/units", headers=sindh_admin).json()[0]["path"].endswith("Sindh PDMA")
    assert c.patch("/api/admin/users/test_officer", headers=sindh_admin, json={"active": False}).status_code == 403   # a user outside the tree
    assert c.patch("/api/admin/users/sindh_admin", headers=sindh_admin, json={"active": False}).status_code == 400    # not oneself
    t = auth.make_token("kar_new")
    assert c.patch("/api/admin/users/kar_new", headers=sindh_admin, json={"active": False}).status_code == 200
    assert c.get("/api/auth/me", headers=hdr(t)).status_code == 401                          # disabling ends the session at once
    reset = c.post("/api/admin/users/kar_new/reset-password", headers=sindh_admin).json()
    assert auth.check_password(reset["temporary_password"], auth.users()["kar_new"]["pw"]) and auth.users()["kar_new"]["must_change"]
    assert c.post("/api/admin/units", headers=sindh_admin, json={"name": "Hyderabad team", "parent": tree["sindh"]}).status_code == 200
    assert c.patch(f"/api/admin/units/{tree['sindh']}", headers=sindh_admin, json={"parent": tree["karachi"]}).status_code == 400   # no cycles
    log = [e["action"] for e in audit.read()]
    assert {"user_create", "user_update", "password_reset", "unit_create"} <= set(log)


def test_audit_log_is_scoped_to_the_callers_unit_tree(tree):
    sindh_admin, pun_admin = mk("sindh_admin", "admin", tree["sindh"]), mk("pun_admin", "admin", tree["punjab"])
    kar = mk("kar_a", "analyst", tree["karachi"])
    c.get("/api/scenes", headers=kar)
    c.get("/api/admin/users", headers=kar)                     # denied: logged with the Karachi unit
    seen = lambda h: {e["actor"] for e in c.get("/api/audit", headers=h).json()}
    assert "kar_a" in seen(sindh_admin) and "kar_a" not in seen(pun_admin)


def test_only_an_administrator_changes_the_approved_model_and_it_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "models", lambda: {"unet_a": {"kind": "unet"}, "unet_b": {"kind": "unet"}, "clf": {"kind": "classifier"}})
    top = next(iter(auth.units()))
    adm, ana = mk("model_admin", "admin", top), mk("model_analyst", "analyst", top)
    body = {"model_id": "unet_b", "reason": "ablation shows the gain is from augmentation"}
    assert c.put("/api/admin/approved-model", headers=ana, json=body).status_code == 403
    assert c.put("/api/admin/approved-model", headers=adm, json={**body, "reason": "short"}).status_code == 400
    assert c.put("/api/admin/approved-model", headers=adm, json={**body, "model_id": "clf"}).status_code == 400
    r = c.put("/api/admin/approved-model", headers=adm, json=body)
    assert r.status_code == 200 and r.json()["default_model"] == "unet_b" and r.json()["previous"] == "unet_paired_mis"
    assert json.loads(engines.APPROVED.read_text())["default_model"] == "unet_b"
    row = (tmp_path / "decision_log.md").read_text()
    assert "unet_b" in row and "model_admin" in row and "ablation shows" in row
    last = audit.read()[-1]
    assert last["action"] == "model_approval" and last["actor"] == "model_admin"
    assert c.get("/api/approved-model", headers=ana).json()["default_model"] == "unet_b"          # anyone signed in can read it


def test_roles_hold_the_expected_permissions():
    p = auth.PERMS
    assert "approve" in p["officer"] and "approve" not in p["analyst"] and "export" not in p["analyst"]
    assert not (p["admin"] & {"view", "review", "approve", "export", "assess", "upload"})
    assert not (p["auditor"] & {"view", "review", "approve", "export", "assess", "upload", "users"})
    assert reviews.STATUSES.index("proposed") < reviews.STATUSES.index("confirmed")
