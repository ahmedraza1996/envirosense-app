"""Approval requests: a sensitive change takes effect only when a different eligible person approves it (schema wf).

Three kinds (wf.approval_policy): the approved default model, a threshold that alters what the application flags, and the permissions of a custom role.
Whoever asks files a request; a different active user who holds the approving permission approves or rejects it (a rejection needs a reason); only then is the
change made, inside the same database transaction as the decision, so it is either decided and applied or neither. The database holds the rules too: the decider
is not the requester, a decided request cannot be edited, one pending request per subject.

When nobody else holds the approving permission (a new installation with one administrator) the change is applied at once and the request is recorded as
self-approved; the database refuses that flag as soon as another eligible approver exists. Requests that nobody decides expire after the policy's days.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import exc as sa_exc

from ..db import semantic
from ..db.engine import engine, one, rows, run, tx
from . import audit, auth, engines

DECISION_LOG = engines.APPROVED.parent / "decision_log.md"
_STAMP = "YYYY-MM-DD HH24:MI:SS"


class _Failed(Exception):
    """The change no longer applies at decision time; raised inside the transaction so the decision and the change are both rolled back."""


class ApprovalError(ValueError):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _label(u: dict) -> str:
    return f"{u['username']} ({u['name']})"


def policy(kind: str) -> dict:
    with tx() as c:
        p = one(c, "SELECT kind, approver_permission, ttl_days, description FROM wf.approval_policy WHERE kind = :k", k=kind)
    if not p:
        raise ApprovalError(f"unknown kind of request {kind}")
    return p


def eligible(kind: str, exclude: str | None = None) -> list:
    """Active users who may decide a request of this kind (the requester excluded)."""
    perm = policy(kind)["approver_permission"]
    with tx() as c:
        return [r["username"] for r in rows(c, "SELECT u.username FROM iam.users u JOIN iam.role_permissions rp ON rp.role_key = u.role "
                                               "WHERE u.active AND rp.permission_key = :p AND u.username <> COALESCE(:x, '') ORDER BY 1", p=perm, x=exclude)]


def expire_old() -> int:
    with tx() as c:
        return run(c, "UPDATE wf.approval_requests SET state = 'expired' WHERE state = 'pending' AND expires_at < now()").rowcount


# ---- applying a change ----------------------------------------------------------------------------------------

def _apply(kind: str, subject: str, payload: dict, requester: str, approver_label: str, rid: int | None, c) -> dict:
    ref = f"approval request {rid}" if rid else "direct change"
    if kind == "model_approval":
        semantic.approve_model(subject, approver_label, payload["reason"], decision_ref=ref, c=c)
        return {"model": subject}
    if kind == "threshold_change":
        semantic.set_threshold(subject, float(payload["value"]), requester, ref, payload["reason"], c=c)
        return {"threshold": subject, "value": float(payload["value"])}
    if kind == "role_permissions":
        before = next((r["permissions"] for r in auth.list_roles() if r["key"] == subject), None)
        if before is None:
            raise KeyError(subject)
        auth.set_role_permissions(subject, payload["permissions"], c=c)
        return {"role": subject, "before": before, "after": sorted(set(payload["permissions"]))}
    raise ApprovalError(f"unknown kind of request {kind}")


def validate(kind: str, subject: str, payload: dict, requester: str) -> None:
    """Run the change inside a transaction and roll it back: everything that would refuse it later refuses it now."""
    with engine().connect() as conn:
        trans = conn.begin()
        try:
            _apply(kind, subject, payload, requester, requester, None, conn)
        finally:
            trans.rollback()
    semantic._threshold_cache.pop(subject, None)
    auth.invalidate_roles()


def _after(kind: str, subject: str, payload: dict, requester: str, approver: str, rid: int, outcome: dict, self_approved: bool) -> None:
    """Records the change once it has been committed: the audit log and, for the default model, a row in the decision log."""
    semantic._threshold_cache.pop(subject, None)
    auth.invalidate_roles()
    how = {"request": rid, "requested_by": requester, "approved_by": approver, "self_approved": self_approved}
    if kind == "model_approval":
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old = outcome.get("previous")
        with DECISION_LOG.open("a") as f:
            f.write(f"| {day} | Application default model changed to `{subject}` (approval request {rid}) | {payload['reason'].replace('|', '/')} | "
                    f"{requester}{'' if self_approved else ', approved by ' + approver} | [supervisor, pending] |\n")
        audit.log("model_approval", approver, previous=old, model=subject, reason=payload["reason"], **how)
    elif kind == "threshold_change":
        audit.log("threshold_change", approver, key=subject, previous=outcome.get("previous"), value=payload["value"], reason=payload["reason"], **how)
    elif kind == "role_permissions":
        audit.log("role_permissions_change", approver, role=subject, before=outcome["before"], after=outcome["after"], reason=payload["reason"], **how)


# ---- requests -------------------------------------------------------------------------------------------------

def submit(kind: str, subject: str, payload: dict, user: dict) -> dict:
    """File a request. Returns {"status": "pending"|"applied", "id": ..., "approvers": n}; the change is made at once only when nobody else may approve it."""
    expire_old()
    pol = policy(kind)
    me = user["username"]
    validate(kind, subject, payload, me)
    others = eligible(kind, exclude=me)
    prev = semantic.approved_id() if kind == "model_approval" else (semantic.threshold(subject) if kind == "threshold_change" else None)
    try:
        with tx() as c:
            rid = one(c, "INSERT INTO wf.approval_requests (kind, subject, payload, requested_by, requested_unit, expires_at) "
                         "VALUES (:k, :s, CAST(:p AS jsonb), :b, :u, now() + make_interval(days => :d)) RETURNING id",
                      k=kind, s=subject, p=json.dumps(payload), b=me, u=user["unit"], d=pol["ttl_days"])["id"]
            if not others:
                outcome = _apply(kind, subject, payload, me, _label(user), rid, c)
                outcome["previous"] = prev
                run(c, "UPDATE wf.approval_requests SET state = 'approved', self_approved = true, decided_by = :b, decided_at = now(), "
                       "decision_note = 'only eligible approver', outcome = CAST(:o AS jsonb) WHERE id = :i", b=me, i=rid, o=json.dumps(outcome))
    except sa_exc.IntegrityError as e:
        if "approval_one_pending" in str(e):
            raise ApprovalError("a request for this is already waiting for approval", 409) from e
        raise
    if others:
        audit.log("approval_request", me, request=rid, kind=kind, subject=subject, waiting_for=len(others))
        return {"status": "pending", "id": rid, "approvers": len(others)}
    _after(kind, subject, payload, me, me, rid, outcome, True)
    return {"status": "applied", "id": rid, "approvers": 0}


def decide(rid: int, user: dict, approve: bool, note: str = "") -> dict:
    note = (note or "").strip()
    if not approve and len(note) < 5:
        raise ApprovalError("give the reason for rejecting (at least 5 characters)")
    expire_old()
    failure = None
    try:
        with tx() as c:
            r = one(c, "SELECT * FROM wf.approval_requests WHERE id = :i FOR UPDATE", i=rid)
            if not r:
                raise KeyError(rid)
            if r["state"] != "pending":
                raise ApprovalError(f"this request is already {r['state']}", 409)
            pol = policy(r["kind"])
            if pol["approver_permission"] not in auth.perms_of(user["role"]) or (r["kind"] == "role_permissions" and not auth.is_top(user)):
                raise ApprovalError("you may not decide this kind of request", 403)
            if user["username"] == r["requested_by"]:
                raise ApprovalError("a different person must decide a request you filed; you can withdraw it", 403)
            payload = r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])
            if not approve:
                run(c, "UPDATE wf.approval_requests SET state = 'rejected', decided_by = :b, decided_at = now(), decision_note = :n WHERE id = :i", b=user["username"], n=note, i=rid)
            else:
                prev = semantic.approved_id() if r["kind"] == "model_approval" else (semantic.threshold(r["subject"]) if r["kind"] == "threshold_change" else None)
                try:
                    outcome = _apply(r["kind"], r["subject"], payload, r["requested_by"], _label(user), rid, c)
                except Exception as e:  # noqa: BLE001  the change no longer applies (a role gained a conflict, a model vanished): the request fails, nothing is changed
                    raise _Failed(f"{type(e).__name__}: {e}") from e
                outcome["previous"] = prev
                run(c, "UPDATE wf.approval_requests SET state = 'approved', decided_by = :b, decided_at = now(), decision_note = :n, outcome = CAST(:o AS jsonb) WHERE id = :i",
                    b=user["username"], n=note or None, i=rid, o=json.dumps(outcome))
    except _Failed as f:
        failure = str(f)
    if failure:
        with tx() as c:
            run(c, "UPDATE wf.approval_requests SET state = 'failed', decided_by = :b, decided_at = now(), decision_note = :n, outcome = CAST(:o AS jsonb) WHERE id = :i",
                b=user["username"], n=note or None, i=rid, o=json.dumps({"error": failure}))
        audit.log("approval_failed", user["username"], request=rid, kind=r["kind"], subject=r["subject"], error=failure)
        raise ApprovalError("the change could not be made, so nothing was changed: " + failure.split(": ", 1)[-1])
    if approve:
        _after(r["kind"], r["subject"], payload, r["requested_by"], user["username"], rid, outcome, False)
    audit.log("approval_decision", user["username"], request=rid, kind=r["kind"], subject=r["subject"], decision="approved" if approve else "rejected", note=note)
    return get(rid)


def withdraw(rid: int, user: dict) -> dict:
    with tx() as c:
        r = one(c, "SELECT state, requested_by FROM wf.approval_requests WHERE id = :i FOR UPDATE", i=rid)
        if not r:
            raise KeyError(rid)
        if r["requested_by"] != user["username"]:
            raise ApprovalError("only the person who filed a request withdraws it", 403)
        if r["state"] != "pending":
            raise ApprovalError(f"this request is already {r['state']}", 409)
        run(c, "UPDATE wf.approval_requests SET state = 'withdrawn', decided_at = now() WHERE id = :i", i=rid)
    audit.log("approval_withdrawn", user["username"], request=rid)
    return get(rid)


_COLS = (f"r.id, r.kind, r.subject, r.payload, r.state, r.requested_by, r.requested_unit, r.decided_by, r.decision_note, r.self_approved, r.outcome, "
         f"to_char(r.requested_at AT TIME ZONE 'UTC', '{_STAMP}') AS requested_utc, to_char(r.expires_at AT TIME ZONE 'UTC', '{_STAMP}') AS expires_utc, "
         f"to_char(r.decided_at AT TIME ZONE 'UTC', '{_STAMP}') AS decided_utc, p.approver_permission, p.description")


def get(rid: int) -> dict:
    with tx() as c:
        r = one(c, f"SELECT {_COLS} FROM wf.approval_requests r JOIN wf.approval_policy p ON p.kind = r.kind WHERE r.id = :i", i=rid)
    if not r:
        raise KeyError(rid)
    return r


def list_requests(user: dict, state: str | None = None, limit: int = 100) -> list:
    """Requests the user filed, and those they may decide."""
    expire_old()
    mine = auth.perms_of(user["role"])
    with tx() as c:
        rs = rows(c, f"SELECT {_COLS} FROM wf.approval_requests r JOIN wf.approval_policy p ON p.kind = r.kind "
                     f"WHERE (r.requested_by = :u OR p.approver_permission = ANY(:perms)) AND (CAST(:s AS text) IS NULL OR r.state = :s) ORDER BY r.id DESC LIMIT :n",
                  u=user["username"], perms=sorted(mine), s=state, n=min(max(limit, 1), 500))
    for r in rs:
        r["can_decide"] = (r["state"] == "pending" and r["requested_by"] != user["username"] and r["approver_permission"] in mine
                           and (r["kind"] != "role_permissions" or auth.is_top(user)))
        r["can_withdraw"] = r["state"] == "pending" and r["requested_by"] == user["username"]
    return rs
