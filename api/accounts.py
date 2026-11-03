"""Routes for signing in, users, units and the approved model (controls A1-A6)."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..db import semantic
from . import audit, auth, engines, service

router = APIRouter()
DECISION_LOG = engines.APPROVED.parent / "decision_log.md"


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
    if username == auth.actor() and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(400, "you cannot disable yourself or take away your own administrator role")
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


# ---- approved model -------------------------------------------------------------------------------------------

@router.get("/api/approved-model")
def approved_model():
    return {**semantic.approved_model(), "available": [{"id": k, "label": m.get("label", k)} for k, m in service.models().items() if m.get("kind") == "unet"]}


@router.put("/api/admin/approved-model")
def approve_model(body: ModelApproval):
    """Change the default model: recorded in sem.model_versions (one approved row at a time), in the audit log and, as a new row, in governance/decision_log.md."""
    models = service.models()
    reason = body.reason.strip()
    if body.model_id not in models or models[body.model_id]["kind"] != "unet":
        raise HTTPException(400, "the default must be an available full-image U-Net model")
    if len(reason) < 10:
        raise HTTPException(400, "give the reason (at least 10 characters)")
    old = semantic.approved_id()
    me = auth.current()
    day = auth.now()[:10]
    semantic.sync_models(models)
    semantic.approve_model(body.model_id, f"{me['username']} ({me['name']})", reason)
    row = f"| {day} | Application default model changed from `{old}` to `{body.model_id}` | {reason.replace('|', '/')} | {me['username']} | [supervisor, pending] |\n"
    with DECISION_LOG.open("a") as f:
        f.write(row)
    audit.log("model_approval", me["username"], previous=old, model=body.model_id, reason=reason)
    return approved_model()
