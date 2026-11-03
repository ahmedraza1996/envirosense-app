"""Routes for signing in, users, units and the approved model (controls A1-A6)."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from fastapi.responses import JSONResponse

from ..db import semantic
from . import approvals, audit, auth, service

router = APIRouter()


class Login(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


class NewUser(BaseModel):
    username: str
    name: str
    role: str
    unit: str
    password: str | None = None


class UserEdit(BaseModel):
    name: str | None = None
    role: str | None = None
    unit: str | None = None
    active: bool | None = None


class NewUnit(BaseModel):
    name: str
    parent: str


class UnitEdit(BaseModel):
    name: str | None = None
    parent: str | None = None


class NewRole(BaseModel):
    key: str
    label: str
    description: str = ""
    permissions: list[str] = []
    based_on: str | None = None


class RolePermissions(BaseModel):
    permissions: list[str]
    reason: str


class ModelApproval(BaseModel):
    model_id: str
    reason: str


def _me() -> dict:
    u = auth.current()
    return auth.public_user(u["username"], auth.get_user(u["username"]))


def _managed(unit_id: str):
    if not auth.manages(auth.current(), unit_id):
        raise HTTPException(403, "that unit is outside your own unit and the units below it")


@router.post("/api/auth/login")
def login(body: Login, request: Request, response: Response):
    try:
        user, token = auth.login(body.username, body.password, request.client.host if request.client else None)
    except auth.AuthError as e:
        audit.log("login_failed", body.username.strip().lower() or "unknown", username=body.username.strip().lower()[:32], reason=str(e),
                  client=request.client.host if request.client else None)
        raise HTTPException(401 if "wrong" in str(e) else 429, str(e))
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_HOURS * 3600, path="/")
    audit.log("login", user["username"], unit=user["unit"], role=user["role"])
    return {**user, "token": token}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE) or (request.headers.get("authorization", "")[7:] or None)
    u = auth.user_from_token(token)
    if u:
        audit.log("logout", u["username"], unit=u["unit"], role=u["role"])
        auth.end_session(token)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me():
    return _me()


@router.post("/api/auth/password")
def change_password(body: PasswordChange, response: Response):
    u = auth.current()
    if not auth.check_password(body.current, u["pw"]):
        raise HTTPException(400, "the current password is wrong")
    if body.new == body.current:
        raise HTTPException(400, "choose a different password")
    try:
        auth.set_password(u["username"], body.new, False)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("password_change", u["username"])
    token = auth.make_token(u["username"])          # other sessions end; this one continues
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_HOURS * 3600, path="/")
    return {"ok": True}


# ---- administration -------------------------------------------------------------------------------------------

@router.get("/api/admin/units")
def get_units():
    me = auth.current()
    vis = auth.visible_units(me)
    counts = {}
    for rec in auth.users().values():
        counts[rec["unit"]] = counts.get(rec["unit"], 0) + 1
    all_units = auth.units()
    return [{"id": k, **v, "path": auth.path_names(k, all_units), "users": counts.get(k, 0)} for k, v in all_units.items() if k in vis]


@router.post("/api/admin/units")
def add_unit(body: NewUnit):
    _managed(body.parent)
    try:
        unit = auth.create_unit(body.name, body.parent, auth.actor())
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("unit_create", auth.actor(), unit=unit["id"], name=unit["name"], parent=body.parent)
    return unit


@router.patch("/api/admin/units/{unit_id}")
def edit_unit(unit_id: str, body: UnitEdit):
    _managed(unit_id)
    if body.parent is not None:
        _managed(body.parent)
    try:
        unit = auth.update_unit(unit_id, body.name, body.parent, move=body.parent is not None)
    except KeyError:
        raise HTTPException(404, f"no unit {unit_id}")
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("unit_update", auth.actor(), unit=unit_id, name=body.name, parent=body.parent)
    return unit


@router.get("/api/admin/users")
def get_users():
    return auth.list_users(auth.visible_units(auth.current()))


@router.post("/api/admin/users")
def add_user(body: NewUser):
    _managed(body.unit)
    pw = body.password or auth.temp_password() + "Aa1"
    try:
        user = auth.create_user(body.username, body.name, body.role, body.unit, pw, auth.actor())
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("user_create", auth.actor(), user=user["username"], role=user["role"], target_unit=user["unit"])
    return {**user, "temporary_password": None if body.password else pw}


@router.patch("/api/admin/users/{username}")
def edit_user(username: str, body: UserEdit):
    rec = auth.get_user(username)
    if not rec:
        raise HTTPException(404, f"no user {username}")
    _managed(rec["unit"])
    if body.unit is not None:
        _managed(body.unit)
    if username == auth.actor() and (body.active is False or (body.role and "users" not in auth.perms_of(body.role))):
        raise HTTPException(400, "you cannot disable yourself or take away your own right to manage users")
    try:
        user = auth.update_user(username, **body.model_dump())
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("user_update", auth.actor(), user=username, **{k: v for k, v in body.model_dump().items() if v is not None})
    return user


@router.post("/api/admin/users/{username}/reset-password")
def reset_password(username: str):
    rec = auth.get_user(username)
    if not rec:
        raise HTTPException(404, f"no user {username}")
    _managed(rec["unit"])
    pw = auth.temp_password() + "Aa1"
    auth.set_password(username, pw, True)
    audit.log("password_reset", auth.actor(), user=username)
    return {"username": username, "temporary_password": pw}


# ---- roles and permissions (schema iam; shared by the whole organisation, so the top unit manages them) -------------

def _top_only():
    if not auth.is_top(auth.current()):
        raise HTTPException(403, "roles are shared by the whole organisation; only an administrator of the top unit changes them")


@router.get("/api/admin/roles")
def get_roles():
    return auth.list_roles()


@router.get("/api/admin/permissions")
def get_permissions():
    return auth.list_permissions()


@router.get("/api/admin/route-policy")
def get_route_policy():
    """Which permission each route needs (first matching rule wins). Changed by migration, not here: a new route needs a rule written with it."""
    return auth.route_rules()


@router.post("/api/admin/roles")
def add_role(body: NewRole):
    _top_only()
    perms = list(body.permissions)
    if body.based_on:
        base = next((r for r in auth.list_roles() if r["key"] == body.based_on), None)
        if base is None:
            raise HTTPException(400, f"no role {body.based_on} to base this on")
        perms = sorted(set(base["permissions"]) | set(perms))
    try:
        role = auth.create_role(body.key, body.label, body.description, perms, auth.actor())
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("role_create", auth.actor(), role=role["key"], permissions=role["permissions"], based_on=body.based_on)
    return role


@router.put("/api/admin/roles/{key}/permissions")
def put_role_permissions(key: str, body: RolePermissions):
    _top_only()
    if len(body.reason.strip()) < 10:
        raise HTTPException(400, "give the reason (at least 10 characters)")
    role = next((r for r in auth.list_roles() if r["key"] == key), None)
    if role is None:
        raise HTTPException(404, f"no role {key}")
    if role["builtin"]:
        raise HTTPException(400, "the permissions of a built-in role cannot be changed; create a role based on it")
    res = submit_request("role_permissions", key, {"permissions": body.permissions, "reason": body.reason.strip()})
    if res["status"] == "pending":
        return JSONResponse(status_code=202, content={"approval": res})
    return {**next(r for r in auth.list_roles() if r["key"] == key), "approval": res}


@router.delete("/api/admin/roles/{key}")
def remove_role(key: str):
    _top_only()
    try:
        auth.delete_role(key)
    except KeyError:
        raise HTTPException(404, f"no role {key}")
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    audit.log("role_delete", auth.actor(), role=key)
    return {"deleted": key}


# ---- approved model -------------------------------------------------------------------------------------------

@router.get("/api/approved-model")
def approved_model():
    return {**semantic.approved_model(), "available": [{"id": k, "label": m.get("label", k)} for k, m in service.models().items() if m.get("kind") == "unet"]}


def submit_request(kind: str, subject: str, payload: dict) -> dict:
    """File an approval request for the signed-in user; the change is made at once only when nobody else may approve it (see api/approvals.py)."""
    try:
        return approvals.submit(kind, subject, payload, auth.current())
    except approvals.ApprovalError as e:
        raise HTTPException(e.status, str(e))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"cannot make this change: {e}")


@router.put("/api/admin/approved-model")
def approve_model(body: ModelApproval):
    """Request a change of the default model. When another administrator may approve it, it waits for them; otherwise it is made at once. Recorded in
    sem.model_versions (one approved row at a time), the audit log and, as a new row, governance/decision_log.md."""
    models = service.models()
    reason = body.reason.strip()
    if body.model_id not in models or models[body.model_id]["kind"] != "unet":
        raise HTTPException(400, "the default must be an available full-image U-Net model")
    if len(reason) < 10:
        raise HTTPException(400, "give the reason (at least 10 characters)")
    semantic.sync_models(models)
    res = submit_request("model_approval", body.model_id, {"model_id": body.model_id, "reason": reason})
    if res["status"] == "pending":
        return JSONResponse(status_code=202, content={**approved_model(), "approval": res})
    return {**approved_model(), "approval": res}
