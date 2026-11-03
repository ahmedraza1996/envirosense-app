"""Approval requests: a sensitive change takes effect only when a different eligible person approves it."""
import pytest
import sqlalchemy as sa
from sqlalchemy import exc
from starlette.testclient import TestClient

from app.api import approvals, audit, auth, engines
from app.api.main import app
from app.db import engine as dbe
from app.db import semantic
from app.tests.conftest import only_admin

c = TestClient(app)


def admin(name, unit=None):
    auth.create_user(name, name.replace("_", " ").title(), "admin", unit or next(iter(auth.units())), "Passw0rd-long-1", "t", must_change=False)
    return {"Authorization": f"Bearer {auth.make_token(name)}"}


def two_admins():
    """Exactly two active administrators: each can approve what the other asks."""
    h1, h2 = admin("admin_one"), admin("admin_two")
    for name, rec in auth.users().items():
        if rec["role"] == "admin" and name not in ("admin_one", "admin_two") and rec["active"]:
            auth.update_user(name, active=False)
    return h1, h2


@pytest.fixture(autouse=True)
def _models(monkeypatch):
    from app.api import service
    monkeypatch.setattr(service, "models", lambda: {"unet_paired_ext": {"kind": "unet"}, "unet_paired_mis": {"kind": "unet"}})
    semantic.sync_models({"unet_paired_ext": {"kind": "unet", "label": "E14"}, "unet_paired_mis": {"kind": "unet", "label": "E15"}})


def test_with_two_administrators_a_model_change_waits_for_the_other():
    h1, h2 = two_admins()
    r = c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_ext", "reason": "the control run shows the extra epochs decide the score"})
    assert r.status_code == 202 and r.json()["approval"]["status"] == "pending"
    assert semantic.approved_id() == "unet_paired_mis"                              # nothing changed yet
    rid = r.json()["approval"]["id"]
    assert c.post(f"/api/approvals/{rid}/approve", headers=h1, json={}).status_code == 403          # the requester cannot approve their own request
    mine, theirs = c.get("/api/approvals", headers=h1).json(), c.get("/api/approvals", headers=h2).json()
    assert [(x["id"], x["can_decide"], x["can_withdraw"]) for x in mine] == [(rid, False, True)]
    assert [(x["id"], x["can_decide"], x["can_withdraw"]) for x in theirs] == [(rid, True, False)]
    d = c.post(f"/api/approvals/{rid}/approve", headers=h2, json={"note": "agreed after reading the log"})
    assert d.status_code == 200 and d.json()["state"] == "approved" and d.json()["decided_by"] == "admin_two"
    assert semantic.approved_id() == "unet_paired_ext" and semantic.approved_model()["approved_by"].startswith("admin_two")
    assert "approved by admin_two" in approvals.DECISION_LOG.read_text() and "unet_paired_ext" in approvals.DECISION_LOG.read_text()
    acts = [(e["action"], e["actor"]) for e in audit.read(limit=50) if e["action"] in ("approval_request", "approval_decision", "model_approval")]
    assert acts == [("approval_request", "admin_one"), ("model_approval", "admin_two"), ("approval_decision", "admin_two")]
    assert c.post(f"/api/approvals/{rid}/approve", headers=h2, json={}).status_code == 409           # a decided request is final
    with pytest.raises(exc.DBAPIError, match="cannot be changed"):
        with dbe.tx("owner") as conn:
            conn.execute(sa.text("UPDATE wf.approval_requests SET decision_note = 'edited' WHERE id = :i"), {"i": rid})


def test_rejection_needs_a_reason_leaves_everything_as_it_was_and_the_requester_can_withdraw():
    h1, h2 = two_admins()
    rid = c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_ext", "reason": "try the older model for the field test"}).json()["approval"]["id"]
    assert c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_ext", "reason": "asking a second time for it"}).status_code == 409   # one pending per subject
    assert c.post(f"/api/approvals/{rid}/reject", headers=h2, json={"note": "no"}).status_code == 400
    r = c.post(f"/api/approvals/{rid}/reject", headers=h2, json={"note": "E15 stays until the augmentation run is in"})
    assert r.json()["state"] == "rejected" and semantic.approved_id() == "unet_paired_mis"
    rid2 = c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_ext", "reason": "asking again after the answer"}).json()["approval"]["id"]
    assert c.post(f"/api/approvals/{rid2}/withdraw", headers=h2).status_code == 403                  # only the requester withdraws
    assert c.post(f"/api/approvals/{rid2}/withdraw", headers=h1).json()["state"] == "withdrawn"


def test_one_administrator_alone_changes_at_once_and_the_database_refuses_that_flag_once_another_exists():
    h1 = admin("only_admin")
    only_admin("only_admin")
    r = c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_ext", "reason": "no other administrator exists yet"})
    assert r.status_code == 200 and r.json()["approval"]["status"] == "applied" and semantic.approved_id() == "unet_paired_ext"
    row = approvals.get(r.json()["approval"]["id"])
    assert row["self_approved"] and row["state"] == "approved" and row["decided_by"] == "only_admin"
    admin("second_admin")                                                                              # now someone else could decide
    with pytest.raises(exc.DBAPIError, match="another eligible approver exists"):
        with dbe.tx() as conn:
            conn.execute(sa.text("INSERT INTO wf.approval_requests (kind, subject, payload, requested_by, expires_at, state, self_approved, decided_by) "
                                 "VALUES ('model_approval', 'x', '{}', 'only_admin', now() + interval '1 day', 'approved', true, 'only_admin')"))
    r2 = c.put("/api/admin/approved-model", headers=h1, json={"model_id": "unet_paired_mis", "reason": "back to the other model now"})
    assert r2.status_code == 202                                                                       # and the application asks for the second person


def test_a_threshold_change_and_a_role_change_need_the_second_person_too():
    h1, h2 = two_admins()
    r = c.put("/api/admin/thresholds/review_confidence", headers=h1, json={"value": 0.75, "reason": "reviewers can take fewer structures"})
    assert r.status_code == 202 and engines.review_confidence() == 0.7
    c.post(f"/api/approvals/{r.json()['approval']['id']}/approve", headers=h2, json={})
    assert engines.review_confidence() == 0.75 and semantic.threshold_history("review_confidence")[0]["set_by"] == "admin_one"
    auth.create_role("rolex", "Role X", "", ["view"], "t")
    r = c.put("/api/admin/roles/rolex/permissions", headers=h1, json={"permissions": ["view", "upload"], "reason": "this role also adds imagery"})
    assert r.status_code == 202 and auth.perms_of("rolex") == {"view"}
    c.post(f"/api/approvals/{r.json()['approval']['id']}/approve", headers=h2, json={})
    assert auth.perms_of("rolex") == {"view", "upload"}
    e = [x for x in audit.read(limit=80) if x["action"] == "role_permissions_change"][-1]
    assert e["detail"]["approved_by"] == "admin_two" and e["detail"]["requested_by"] == "admin_one" and e["detail"]["after"] == ["upload", "view"]


def test_a_request_that_could_never_apply_is_refused_when_filed_and_one_that_stops_applying_fails_without_changing_anything():
    h1, h2 = two_admins()
    auth.create_role("rolez", "Role Z", "", ["view"], "t")
    bad = c.put("/api/admin/roles/rolez/permissions", headers=h1, json={"permissions": ["view", "users"], "reason": "an impossible combination"})
    assert bad.status_code == 400 and "cannot hold both" in bad.text and c.get("/api/approvals", headers=h1).json() == []      # not even filed
    r = c.put("/api/admin/roles/rolez/permissions", headers=h1, json={"permissions": ["view", "upload"], "reason": "a role that will vanish first"})
    assert r.status_code == 202
    auth.delete_role("rolez")                                                                             # the role is gone before anyone decides
    d = c.post(f"/api/approvals/{r.json()['approval']['id']}/approve", headers=h2, json={})
    assert d.status_code == 400 and "nothing was changed" in d.text
    assert approvals.get(r.json()["approval"]["id"])["state"] == "failed"


def test_requests_expire_and_roles_are_decided_only_by_the_top_unit():
    h1, h2 = two_admins()
    top = next(iter(auth.units()))
    sub = auth.create_unit("Regional", top, "t")["id"]
    sub_admin = admin("regional_admin", sub)
    auth.create_role("roley", "Role Y", "", ["view"], "t")
    rid = c.put("/api/admin/roles/roley/permissions", headers=h1, json={"permissions": ["view", "geo_offset"], "reason": "geo offsets for this role"}).json()["approval"]["id"]
    assert c.post(f"/api/approvals/{rid}/approve", headers=sub_admin, json={}).status_code == 403     # roles are shared: only the top unit decides
    with dbe.tx("owner") as conn:
        conn.execute(sa.text("UPDATE wf.approval_requests SET expires_at = now() - interval '1 hour' WHERE id = :i"), {"i": rid})
    assert c.post(f"/api/approvals/{rid}/approve", headers=h2, json={}).status_code == 409
    assert approvals.get(rid)["state"] == "expired" and auth.perms_of("roley") == {"view"}


def test_people_without_the_approving_permission_see_and_decide_nothing():
    h1, h2 = two_admins()
    rid = c.put("/api/admin/thresholds/review_confidence", headers=h1, json={"value": 0.8, "reason": "stricter review for the exercise"}).json()["approval"]["id"]
    top = next(iter(auth.units()))
    auth.create_user("plain_analyst", "Plain", "analyst", top, "Passw0rd-long-1", "t", must_change=False)
    ana = {"Authorization": f"Bearer {auth.make_token('plain_analyst')}"}
    assert c.get("/api/approvals", headers=ana).json() == []
    assert c.post(f"/api/approvals/{rid}/approve", headers=ana, json={}).status_code == 403
    assert c.post("/api/approvals/9999/approve", headers=h2, json={}).status_code == 404
