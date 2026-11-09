"""The database holds the rules too: constraints and triggers that stand even if the application code has a bug."""
import threading
import time

import pytest
import sqlalchemy as sa
from sqlalchemy import exc
from starlette.testclient import TestClient

from app.api import auth, registry, reviews, uploads
from app.api.main import app
from app.db import engine as dbe
from app.db import semantic
from app.tests.conftest import only_admin
from app.tests.test_governance import _rec

c = TestClient(app)


def sql(statement, **p):
    with dbe.tx() as conn:
        return dbe.rows(conn, statement, **p)


def test_the_database_refuses_a_confirmation_by_the_person_who_proposed():
    reviews.set_review("a", _rec(), "AL-1", "proposed", "ok", "R1", "officer", "u")
    with pytest.raises(exc.IntegrityError, match="four_eyes"):
        with dbe.tx() as conn:                       # not through the application's checks
            conn.execute(sa.text("UPDATE wf.alert_reviews SET status = 'confirmed', reviewed_by = 'R1' WHERE assessment_id = 'a' AND alert_id = 'AL-1'"))
    with pytest.raises(exc.IntegrityError, match="reason_required"):
        with dbe.tx() as conn:
            conn.execute(sa.text("UPDATE wf.alert_reviews SET status = 'dismissed', note = '' WHERE assessment_id = 'a' AND alert_id = 'AL-1'"))
    with pytest.raises(exc.DBAPIError, match="permission denied"):                       # the application's role has no right to edit history
        with dbe.tx() as conn:
            conn.execute(sa.text("UPDATE wf.alert_review_events SET note = 'changed' WHERE assessment_id = 'a'"))
    with pytest.raises(exc.DBAPIError, match="cannot be edited"):                        # and not even the owner of the tables can
        with dbe.tx("owner") as conn:
            conn.execute(sa.text("UPDATE wf.alert_review_events SET note = 'changed' WHERE assessment_id = 'a'"))


def test_two_people_reviewing_the_same_alert_at_once_leave_a_consistent_history():
    rec = _rec()
    reviews.set_review("a", rec, "AL-1", "proposed", "first", "R1", "officer", "u")
    errors = []

    def confirm(who):
        try:
            reviews.set_review("a", rec, "AL-1", "confirmed", "agreed", who, "officer", "u")
        except reviews.ReviewError as e:
            errors.append(str(e))
    ts = [threading.Thread(target=confirm, args=(w,)) for w in ("R2", "R3")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(errors) == 1                                        # the second one finds it already confirmed
    e = reviews.load("a")["alerts"]["AL-1"]
    assert [h["status"] for h in e["history"]] == ["proposed", "confirmed"] and e["status"] == "confirmed"
    assert sql("SELECT seq FROM wf.alert_review_events ORDER BY seq") == [{"seq": 1}, {"seq": 2}]


def test_units_form_a_tree_without_cycles_and_there_is_always_an_administrator():
    top = next(iter(auth.units()))
    a = auth.create_unit("Unit A", top, "t")["id"]
    b = auth.create_unit("Unit B", a, "t")["id"]
    with pytest.raises(auth.AuthError, match="cannot move under itself"):
        auth.update_unit(a, None, b, move=True)
    with pytest.raises(auth.AuthError, match="top unit cannot be moved"):
        auth.update_unit(top, None, a, move=True)
    with pytest.raises(auth.AuthError, match="already exists"):
        auth.create_unit("unit a", top, "t")                        # same name under the same parent, whatever the case
    with pytest.raises(exc.IntegrityError):
        with dbe.tx() as conn:                                       # a second top unit
            conn.execute(sa.text("INSERT INTO iam.units (id, name) VALUES ('u_two', 'Second top')"))
    admin = next(k for k, v in auth.users().items() if v["role"] == "admin")
    with pytest.raises(auth.AuthError, match="at least one active administrator"):
        auth.update_user(admin, active=False)
    with pytest.raises(exc.DBAPIError, match="at least one active administrator"):
        with dbe.tx() as conn:
            conn.execute(sa.text("UPDATE iam.users SET role = 'analyst' WHERE username = :u"), {"u": admin})


def test_a_session_ends_at_once_on_sign_out_password_change_or_deactivation():
    top = next(iter(auth.units()))
    auth.create_user("sess_user", "Sess User", "analyst", top, "Passw0rd-long-1", "t", must_change=False)
    t1, t2 = auth.make_token("sess_user"), auth.make_token("sess_user")
    assert auth.user_from_token(t1) and auth.user_from_token(t2)
    auth.end_session(t1)
    assert auth.user_from_token(t1) is None and auth.user_from_token(t2)
    assert auth.user_from_token(t2[:-1] + ("0" if t2[-1] != "0" else "1")) is None                              # a forged signature
    auth.set_password("sess_user", "Another-long-pass-2", False)
    assert auth.user_from_token(t2) is None
    t3 = auth.make_token("sess_user")
    auth.update_user("sess_user", active=False)
    assert auth.user_from_token(t3) is None


def test_sign_in_lockout_survives_in_the_database_and_covers_unknown_names():
    for _ in range(auth.LOCK_AFTER):
        with pytest.raises(auth.AuthError, match="wrong username or password"):
            auth.login("nobody_here", "wrong-password-1")
    with pytest.raises(auth.AuthError, match="too many failed attempts"):
        auth.login("nobody_here", "wrong-password-1")
    assert sql("SELECT locked_until IS NOT NULL AS locked FROM iam.login_throttle WHERE username = 'nobody_here'") == [{"locked": True}]


# ---- ingestion jobs --------------------------------------------------------------------------------------------

def test_a_job_is_claimed_once_and_a_dead_worker_is_recovered(make_upload):
    top = next(iter(auth.units()))
    u1, u2 = make_upload(top, "t", "one", job=None), make_upload(top, "t", "two", job=None)
    with dbe.tx() as conn:
        for u in (u1, u2):
            dbe.run(conn, "INSERT INTO ingest.jobs (upload_id) VALUES (:u)", u=u)
    with pytest.raises(exc.IntegrityError):                           # one active job per upload
        with dbe.tx() as conn:
            dbe.run(conn, "INSERT INTO ingest.jobs (upload_id) VALUES (:u)", u=u1)
    got = [uploads.claim(), uploads.claim(), uploads.claim()]
    assert [g[1] for g in got[:2]] == [u1, u2] and got[2] is None   # each job once, in order
    with dbe.tx() as conn:
        dbe.run(conn, "UPDATE ingest.jobs SET heartbeat_at = now() - interval '10 minutes' WHERE upload_id = :u", u=u1)
    assert uploads.requeue_stale() == 1                               # the worker of u1 stopped: it goes back to the queue
    assert uploads.claim()[1] == u1
    assert sql("SELECT attempts FROM ingest.jobs WHERE upload_id = :u", u=u1) == [{"attempts": 2}]
    with dbe.tx() as conn:
        dbe.run(conn, "UPDATE ingest.jobs SET heartbeat_at = now() - interval '10 minutes', attempts = max_attempts WHERE upload_id = :u", u=u1)
    uploads.requeue_stale()
    assert uploads.info(u1)["status"]["state"] == "failed" and "ran out of attempts" in uploads.info(u1)["status"]["error"]


def test_the_worker_records_steps_and_the_result(make_upload, monkeypatch):
    top = next(iter(auth.units()))
    uid = make_upload(top, "t", "run", job=None)

    def fake_process(u):
        uploads.set_status(u, step="Reading after image")
        uploads.set_status(u, step="Raising area alerts")
        return {"id": f"{u}__m__area", "alerts": [1, 2]}
    # patched before the job exists: a worker thread left running by an earlier test must not pick it up with the real pipeline
    monkeypatch.setattr(uploads, "process", fake_process)
    monkeypatch.setattr(uploads, "POLL_S", 0.05)
    with dbe.tx() as conn:
        dbe.run(conn, "INSERT INTO ingest.jobs (upload_id) VALUES (:u)", u=uid)
    uploads._ensure_worker()
    for _ in range(100):
        if uploads.info(uid)["status"]["state"] == "done":
            break
        time.sleep(0.1)
    st = uploads.info(uid)["status"]
    assert st["state"] == "done" and st["assessment_id"] == f"{uid}__m__area" and st["alerts"] == 2
    steps = sql("SELECT name, state FROM ingest.job_steps ORDER BY seq")
    assert steps == [{"name": "Reading after image", "state": "ok"}, {"name": "Raising area alerts", "state": "ok"}]
    jobs = c.get("/api/jobs").json()
    assert jobs[0]["upload_id"] == uid and [s["name"] for s in jobs[0]["steps"]] == ["Reading after image", "Raising area alerts"]


# ---- assessments, alerts and geometry --------------------------------------------------------------------------

def test_alerts_are_stored_with_geometry_and_reviewed_alerts_are_never_removed():
    rec = {**_rec(), "id": "geo1", "alerts": [{**_alert_geo("AL-1", 10.0), }, {**_alert_geo("AL-2", 10.1)}]}
    registry.register(rec)
    got = sql("SELECT alert_id, ST_AsText(ST_Centroid(geom)) AS c, ST_IsValid(geom) AS ok FROM core.alerts WHERE assessment_id = 'geo1' ORDER BY alert_id")
    assert [g["alert_id"] for g in got] == ["AL-1", "AL-2"] and all(g["ok"] for g in got)
    assert sql("SELECT ST_GeometryType(footprint) AS t FROM core.assessments WHERE id = 'geo1'") == [{"t": "ST_Polygon"}]
    near = sql("SELECT alert_id FROM core.alerts WHERE assessment_id = 'geo1' AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(10.1005, 38.0005), 4326)::geography, 500)")
    assert near == [{"alert_id": "AL-2"}]                             # a spatial question answered by the database
    reviews.set_review("geo1", rec, "AL-1", "proposed", "ok", "R1", "officer", "u")
    registry.register({**rec, "alerts": [rec["alerts"][1]]})           # a re-run no longer raises AL-1
    assert {r["alert_id"] for r in sql("SELECT alert_id FROM core.alerts WHERE assessment_id = 'geo1'")} == {"AL-1", "AL-2"}   # AL-1 has a review: kept
    registry.register({**rec, "id": "geo2", "alerts": [rec["alerts"][1]]})
    registry.register({**rec, "id": "geo2", "alerts": []})
    assert sql("SELECT count(*) AS n FROM core.alerts WHERE assessment_id = 'geo2'") == [{"n": 0}]                              # no review: removed


def _alert_geo(i, lon):
    ring = [[lon, 38.0], [lon + 1e-3, 38.0], [lon + 1e-3, 38.001], [lon, 38.001], [lon, 38.0]]
    return {"alert_id": i, "severity": "high", "hull_lonlat": ring, "severe_area_m2": 300.0, "building_area_m2": 400.0, "severe_share": 0.75,
            "structures": 4, "severe": 3, "area_m2": 900.0, "centroid_lat": 38.0005, "centroid_lon": lon, "priority": 5.0}


def test_deleting_an_upload_removes_its_jobs_alerts_and_review_history(make_upload):
    top = next(iter(auth.units()))
    uid = make_upload(top, "t", "gone")
    rec = {**_rec(), "id": f"{uid}__m__area", "pair_id": uid, "scene": {"source": "upload"}, "alerts": [_alert_geo("AL-1", 10.0)]}
    registry.register(rec)
    reviews.set_review(rec["id"], rec, "AL-1", "proposed", "ok", "R1", "officer", "u")
    uploads.delete(uid)
    for table in ("ingest.uploads", "ingest.jobs", "core.assessments", "core.alerts", "wf.alert_reviews", "wf.alert_review_events"):
        assert sql(f"SELECT count(*) AS n FROM {table}") == [{"n": 0}], table


# ---- the semantic layer ----------------------------------------------------------------------------------------

def test_semantic_layer_serves_definitions_and_a_changed_threshold_is_versioned_and_logged():
    assert [k["key"] for k in c.get("/api/semantic/classes").json()] == ["no-damage", "minor-damage", "major-damage", "destroyed"]
    assert {m["key"] for m in c.get("/api/semantic/metrics").json()} >= {"xview2_score", "severe_share", "priority_score"}
    assert any(g["term"] == "four-eyes rule" for g in c.get("/api/semantic/glossary").json())
    assert c.get("/api/semantic/thresholds").json()[0]["value"] == 0.7
    ana = {"Authorization": f"Bearer {auth.make_token(_user('sem_analyst', 'analyst'))}"}
    adm = {"Authorization": f"Bearer {auth.make_token(_user('sem_admin', 'admin'))}"}
    only_admin("sem_admin")
    body = {"value": 0.65, "reason": "reviewers ask for more structures to look at"}
    assert c.put("/api/admin/thresholds/review_confidence", headers=ana, json=body).status_code == 403
    assert c.put("/api/admin/thresholds/review_confidence", headers=adm, json={**body, "reason": "no"}).status_code == 400
    assert c.put("/api/admin/thresholds/review_confidence", headers=adm, json={**body, "value": 1.5}).status_code == 400
    assert c.put("/api/admin/thresholds/other_key", headers=adm, json=body).status_code == 400
    assert c.put("/api/admin/thresholds/review_confidence", headers=adm, json=body).status_code == 200
    from app.api import engines
    assert engines.review_confidence() == 0.65
    hist = c.get("/api/semantic/thresholds/review_confidence/history").json()
    assert [h["value"] for h in hist] == [0.65, 0.7] and hist[0]["set_by"] == "sem_admin"
    last = [e for e in c.get("/api/audit", headers=adm).json() if e["action"] == "threshold_change"][-1]
    assert last["detail"]["previous"] == 0.7 and last["detail"]["value"] == 0.65


def test_exactly_one_model_version_is_approved_and_it_needs_an_approver():
    semantic.sync_models({"unet_x": {"kind": "unet", "label": "X"}, "unet_y": {"kind": "unet", "label": "Y"}, "unet_z": {"kind": "unet", "label": "Z"}})
    semantic.approve_model("unet_x", "t", "first approval for the test")
    semantic.approve_model("unet_y", "t", "second approval for the test")
    assert sorted(m["id"] for m in semantic.model_versions() if m["status"] == "approved") == ["unet_y"]
    with pytest.raises(exc.IntegrityError, match="model_one_approved"):
        with dbe.tx() as conn:
            conn.execute(sa.text("UPDATE sem.model_versions SET status = 'approved', approved_by = 't', approved_at = now() WHERE id = 'unet_x'"))
    with pytest.raises(exc.IntegrityError, match="approval_has_approver"):
        with dbe.tx() as conn:
            conn.execute(sa.text("UPDATE sem.model_versions SET status = 'retired' WHERE status = 'approved'"))
            conn.execute(sa.text("UPDATE sem.model_versions SET status = 'approved' WHERE id = 'unet_z'"))      # never approved by anyone


def _user(name, role):
    auth.create_user(name, name, role, next(iter(auth.units())), "Passw0rd-long-1", "t", must_change=False)
    return name


# ---- roles, permissions, route policy as data ------------------------------------------------------------------

def _admin_headers(name="roles_admin", unit=None, sole=True):
    auth.create_user(name, name, "admin", unit or next(iter(auth.units())), "Passw0rd-long-1", "t", must_change=False)
    if sole:
        only_admin(name)
    return {"Authorization": f"Bearer {auth.make_token(name)}"}


def test_built_in_roles_and_the_route_policy_are_rows_with_the_rights_they_always_had():
    assert auth.perms_of("admin") == {"users", "audit", "model_approve"}
    assert auth.perms_of("auditor") == {"audit", "review_read"}
    assert auth.perms_of("analyst") == {"view", "assess", "upload", "delete_own_upload", "review", "review_read", "geo_offset"}
    assert auth.perms_of("officer") == auth.perms_of("analyst") | {"approve", "export", "delete_upload"}
    assert auth.required("GET", "/api/health") == "public" and auth.required("DELETE", "/api/uploads/upl_00000001") == "delete_own_upload"
    assert auth.required("GET", "/api/not-a-route") is None
    assert sql("SELECT count(*) AS n FROM iam.route_policy") == [{"n": 30}]


def test_an_administrator_creates_a_role_and_a_user_holding_it_gets_exactly_those_rights():
    adm = _admin_headers()
    made = c.post("/api/admin/roles", headers=adm, json={"key": "field_lead", "label": "Field team lead", "based_on": "analyst", "permissions": ["export"],
                                                          "description": "An analyst who may export for the field team"})
    assert made.status_code == 200 and "export" in made.json()["permissions"] and "review" in made.json()["permissions"] and not made.json()["builtin"]
    top = next(iter(auth.units()))
    auth.create_user("lead1", "Lead One", "field_lead", top, "Passw0rd-long-1", "t", must_change=False)
    h = {"Authorization": f"Bearer {auth.make_token('lead1')}"}
    me = c.get("/api/auth/me", headers=h).json()
    assert me["role"] == "field_lead" and me["role_label"] == "Field team lead" and "export" in me["permissions"] and "approve" not in me["permissions"]
    assert c.get("/api/admin/users", headers=h).status_code == 403                               # not an administrator
    log = [e for e in c.get("/api/audit", headers=adm).json() if e["action"] == "role_create"][-1]
    assert log["detail"]["role"] == "field_lead" and log["detail"]["based_on"] == "analyst"


def test_a_role_cannot_combine_permissions_that_must_stay_apart():
    with pytest.raises(auth.AuthError, match='cannot hold both "review" and "users"|cannot hold both "users" and "review"'):
        auth.create_role("overreach", "Overreach", "", ["users", "review"], "t")
    with pytest.raises(auth.AuthError, match="cannot hold both"):
        auth.create_role("watcher_doer", "Watcher doer", "", ["audit", "approve"], "t")
    auth.create_role("ok_role", "Fine role", "", ["view", "review"], "t")
    with pytest.raises(auth.AuthError, match="cannot hold both"):
        auth.set_role_permissions("ok_role", ["view", "review", "users"])
    assert auth.perms_of("ok_role") == {"view", "review"}                                       # the refused change left the role as it was
    with pytest.raises(exc.DBAPIError, match="cannot hold both"):                               # and the database refuses it for any writer
        with dbe.tx() as conn:
            conn.execute(sa.text("INSERT INTO iam.role_permissions (role_key, permission_key) VALUES ('ok_role', 'audit')"))


def test_built_in_roles_cannot_be_changed_only_copied():
    with pytest.raises(auth.AuthError, match="built-in"):
        auth.set_role_permissions("analyst", ["view"])
    with pytest.raises(auth.AuthError, match="built-in"):
        auth.delete_role("officer")
    with pytest.raises(exc.DBAPIError, match="built-in"):
        with dbe.tx("owner") as conn:                                                           # not even the owner of the tables
            conn.execute(sa.text("DELETE FROM iam.role_permissions WHERE role_key = 'auditor'"))
    with pytest.raises(exc.IntegrityError):                                                     # 'any' and 'public' are route rules, not rights a role holds
        with dbe.tx() as conn:
            conn.execute(sa.text("INSERT INTO iam.roles (key, label) VALUES ('sneaky', 'Sneaky'); INSERT INTO iam.role_permissions (role_key, permission_key) VALUES ('sneaky', 'any')"))


def test_changing_a_custom_role_takes_effect_at_once_and_is_logged_with_a_reason():
    adm = _admin_headers()
    auth.create_role("reader", "Reader", "", ["view"], "t")
    top = next(iter(auth.units()))
    auth.create_user("reader1", "Reader One", "reader", top, "Passw0rd-long-1", "t", must_change=False)
    h = {"Authorization": f"Bearer {auth.make_token('reader1')}"}
    assert c.get("/api/scenes", headers=h).status_code == 200 and c.post("/api/uploads", headers=h).status_code == 403
    assert c.put("/api/admin/roles/reader/permissions", headers=adm, json={"permissions": ["view", "upload"], "reason": "no"}).status_code == 400
    r = c.put("/api/admin/roles/reader/permissions", headers=adm, json={"permissions": ["view", "upload"], "reason": "readers now add imagery too"})
    assert r.status_code == 200 and r.json()["permissions"] == ["upload", "view"]
    assert c.post("/api/uploads", headers=h).status_code != 403                                  # allowed through the policy (the request itself is incomplete)
    assert c.put("/api/admin/roles/reader/permissions", headers=adm, json={"permissions": ["view", "nonsense"], "reason": "a typo in a permission"}).status_code == 400
    e = [x for x in c.get("/api/audit", headers=adm).json() if x["action"] == "role_permissions_change"][-1]
    assert e["detail"]["before"] == ["view"] and e["detail"]["after"] == ["upload", "view"] and "imagery" in e["detail"]["reason"]


def test_a_role_that_users_hold_cannot_be_deleted_and_only_the_top_unit_manages_roles():
    adm = _admin_headers()
    top = next(iter(auth.units()))
    sub = auth.create_unit("Regional office", top, "t")["id"]
    auth.create_role("temp_role", "Temporary", "", ["view"], "t")
    auth.create_user("holder", "Holder", "temp_role", sub, "Passw0rd-long-1", "t", must_change=False)
    assert c.delete("/api/admin/roles/temp_role", headers=adm).status_code == 400
    sub_adm = _admin_headers("regional_admin", sub, sole=False)
    assert c.post("/api/admin/roles", headers=sub_adm, json={"key": "x_role", "label": "X role"}).status_code == 403         # a unit's administrator manages users, not shared roles
    assert c.get("/api/admin/roles", headers=sub_adm).status_code == 200                                                       # but may read them to assign them
    auth.update_user("holder", role="analyst")
    assert c.delete("/api/admin/roles/temp_role", headers=adm).status_code == 200
    assert "temp_role" not in auth.ROLES


def test_confirming_needs_the_approve_permission_not_a_particular_role_name():
    from app.api import reviews
    auth.create_role("reviewer_lite", "Reviewer lite", "", ["view", "review"], "t")
    auth.create_role("senior_reviewer", "Senior reviewer", "", ["view", "review", "approve"], "t")
    rec = _rec()
    reviews.set_review("a", rec, "AL-1", "proposed", "ok", "P1", "reviewer_lite", "u")
    with pytest.raises(PermissionError):
        reviews.set_review("a", rec, "AL-1", "confirmed", "ok", "P2", "reviewer_lite", "u")
    assert reviews.set_review("a", rec, "AL-1", "confirmed", "ok", "P2", "senior_reviewer", "u")["status"] == "confirmed"
    with pytest.raises(PermissionError):
        reviews.set_review("a", rec, "AL-2", "proposed", "ok", "A1", "auditor", "u")            # the auditor role has no review permission
