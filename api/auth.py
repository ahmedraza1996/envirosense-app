"""Users, organisation units, roles and access checks (controls A1-A6 of governance/control_matrix.md).

An organisation is a tree of units (national authority > provincial department > district team). Every user belongs to one unit and has
one role. A user sees and acts on the data of their own unit and the units below it, never on sibling units. Benchmark (xBD) scenes are shared
demonstration data and are visible to every analyst and officer.

Roles
  admin    manages users and units in their unit and below, sets the approved model, reads the audit log; no access to imagery or alerts
  analyst  assesses, uploads, proposes, dismisses, asks for information; cannot confirm, retract or export
  officer  everything an analyst does, plus confirms another person's proposal, retracts, exports, deletes uploads in the unit tree
  auditor  read-only: audit log, review history, policy; no imagery, alert lists or exports

Sessions are signed tokens in an HttpOnly cookie (or an `Authorization: Bearer` header for scripts); passwords are stored as scrypt hashes.
Every API route needs an entry in POLICY; a route without one is refused (a test enforces this). This is access control for a research
prototype on a private network; it has not been security-tested and is not a substitute for a managed identity service.
"""
import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from .engines import ROOT

DIR = ROOT / "runs" / "app" / "auth"
SESSION_HOURS = 12
MIN_PASSWORD = 10
LOCK_AFTER, LOCK_SECONDS = 5, 300
COOKIE = "es_session"
ROLES = ("admin", "analyst", "officer", "auditor")
ROLE_LABEL = {"admin": "System administrator", "analyst": "Analyst", "officer": "Approving officer", "auditor": "Auditor"}

_ANALYST = {"view", "assess", "upload", "delete_own_upload", "review", "review_read", "geo_offset"}
PERMS = {
    "admin": {"users", "audit", "model_approve"},
    "analyst": _ANALYST,
    "officer": _ANALYST | {"approve", "export", "delete_upload"},
    "auditor": {"audit", "review_read"},
}
# (method, path regex, permission). "any" = every signed-in user, "public" = no sign-in. First match wins; no match = refused.
POLICY = [
    ("GET", r"/api/health", "public"),
    ("POST", r"/api/auth/login", "public"),
    ("POST", r"/api/auth/logout", "public"),
    ("GET", r"/api/auth/me", "any"),
    ("POST", r"/api/auth/password", "any"),
    ("GET", r"/api/policy", "any"),
    ("GET", r"/api/approved-model", "any"),
    ("GET", r"/api/admin/(users|units)", "users"),
    ("(POST|PATCH)", r"/api/admin/(users|units)(/[^/]+)?", "users"),
    ("POST", r"/api/admin/users/[^/]+/reset-password", "users"),
    ("PUT", r"/api/admin/approved-model", "model_approve"),
    ("GET", r"/api/audit(/verify)?", "audit"),
    ("GET", r"/api/assessments/[^/]+/reviews", "review_read"),
    ("PUT", r"/api/assessments/[^/]+/alerts/[^/]+/review", "review"),
    ("GET", r"/api/assessments/[^/]+/export\.(geojson|csv)", "export"),
    ("(PUT|POST)", r"/api/assessments/[^/]+/geo-offset(/measure)?", "geo_offset"),
    ("(POST)", r"/api/(assess|assess-area)", "assess"),
    ("POST", r"/api/events/[^/]+/assess", "assess"),
    ("POST", r"/api/uploads", "upload"),
    ("PATCH", r"/api/uploads/[^/]+", "upload"),
    ("DELETE", r"/api/uploads/[^/]+", "delete_own_upload"),   # an officer may delete any upload in scope; an analyst only their own
    ("GET", r"/api/(models|scenes|uploads|events|assessments)(/.*)?", "view"),
]
_POLICY = [(m, re.compile(r), p) for m, r, p in POLICY]

_lock = threading.Lock()
_fails: dict = {}
_current: contextvars.ContextVar = contextvars.ContextVar("current_user", default=None)


class AuthError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---- storage --------------------------------------------------------------------------------------------------

def _read(name, default):
    p = DIR / name
    return json.loads(p.read_text()) if p.exists() else default


def _write(name, data):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(DIR / name)


def users() -> dict:
    return _read("users.json", {})


def units() -> dict:
    return _read("units.json", {})


def _secret() -> bytes:
    p = DIR / "secret.key"
    if not p.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return p.read_bytes()


# ---- passwords ------------------------------------------------------------------------------------------------

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except ValueError:
        return False


def _policy_check_password(pw: str):
    if len(pw) < MIN_PASSWORD:
        raise AuthError(f"a password needs at least {MIN_PASSWORD} characters")
    if pw.lower() in ("password", "password123", "1234567890", "qwertyuiop"):
        raise AuthError("that password is too common")


# ---- units ----------------------------------------------------------------------------------------------------

def descendants(unit_id: str, all_units: dict | None = None) -> set:
    u = all_units if all_units is not None else units()
    out, todo = {unit_id}, [unit_id]
    while todo:
        cur = todo.pop()
        for k, v in u.items():
            if v.get("parent") == cur and k not in out:
                out.add(k)
                todo.append(k)
    return out


def path_names(unit_id: str) -> str:
    u, parts, seen = units(), [], set()
    while unit_id and unit_id in u and unit_id not in seen:
        seen.add(unit_id)
        parts.append(u[unit_id]["name"])
        unit_id = u[unit_id].get("parent")
    return " > ".join(reversed(parts))


def create_unit(name: str, parent: str | None, by: str) -> dict:
    name = (name or "").strip()
    if not 2 <= len(name) <= 80:
        raise AuthError("a unit name needs 2 to 80 characters")
    with _lock:
        u = units()
        if parent is not None and parent not in u:
            raise AuthError(f"no parent unit {parent}")
        if parent is None and u:
            raise AuthError("there is one top unit; give a parent")
        if any(v["name"].lower() == name.lower() and v.get("parent") == parent for v in u.values()):
            raise AuthError("a unit with that name already exists there")
        uid = "u_" + secrets.token_hex(3)
        u[uid] = {"name": name, "parent": parent, "created_utc": now(), "created_by": by}
        _write("units.json", u)
    return {"id": uid, **u[uid]}


def update_unit(unit_id: str, name: str | None, parent: str | None, move: bool) -> dict:
    with _lock:
        u = units()
        if unit_id not in u:
            raise KeyError(unit_id)
        if name is not None:
            if not 2 <= len(name.strip()) <= 80:
                raise AuthError("a unit name needs 2 to 80 characters")
            u[unit_id]["name"] = name.strip()
        if move:
            if u[unit_id].get("parent") is None:
                raise AuthError("the top unit cannot be moved")
            if parent not in u or parent in descendants(unit_id, u):
                raise AuthError("a unit cannot move under itself or an unknown unit")
            u[unit_id]["parent"] = parent
        _write("units.json", u)
    return {"id": unit_id, **u[unit_id]}


# ---- users ----------------------------------------------------------------------------------------------------

def public_user(name: str, rec: dict) -> dict:
    return {"username": name, "name": rec["name"], "role": rec["role"], "role_label": ROLE_LABEL[rec["role"]], "unit": rec["unit"],
            "unit_name": units().get(rec["unit"], {}).get("name", ""), "unit_path": path_names(rec["unit"]), "active": rec.get("active", True),
            "must_change_password": rec.get("must_change", False), "created_utc": rec.get("created_utc"),
            "last_login_utc": rec.get("last_login_utc"), "permissions": sorted(PERMS[rec["role"]])}


def create_user(username: str, name: str, role: str, unit: str, password: str, by: str, must_change: bool = True) -> dict:
    username = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
        raise AuthError("a username has 3 to 32 characters: letters, digits, dot, dash, underscore")
    if role not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}")
    if not (name or "").strip():
        raise AuthError("a full name is required")
    _policy_check_password(password)
    with _lock:
        u, us = units(), users()
        if unit not in u:
            raise AuthError(f"no unit {unit}")
        if username in us:
            raise AuthError(f"user {username} already exists")
        us[username] = {"name": name.strip()[:80], "role": role, "unit": unit, "pw": hash_password(password), "active": True,
                        "must_change": must_change, "created_utc": now(), "created_by": by, "pwv": secrets.token_hex(4)}
        _write("users.json", us)
    return public_user(username, us[username])


def update_user(username: str, **ch) -> dict:
    with _lock:
        us, u = users(), units()
        if username not in us:
            raise KeyError(username)
        rec = us[username]
        if ch.get("name") is not None:
            if not ch["name"].strip():
                raise AuthError("a full name is required")
            rec["name"] = ch["name"].strip()[:80]
        if ch.get("role") is not None:
            if ch["role"] not in ROLES:
                raise AuthError(f"role must be one of {', '.join(ROLES)}")
            rec["role"] = ch["role"]
        if ch.get("unit") is not None:
            if ch["unit"] not in u:
                raise AuthError(f"no unit {ch['unit']}")
            rec["unit"] = ch["unit"]
        if ch.get("active") is not None:
            rec["active"] = bool(ch["active"])
        if not any(r.get("role") == "admin" and r.get("active", True) for r in us.values()):
            raise AuthError("there must be at least one active administrator")
        rec["pwv"] = secrets.token_hex(4) if ch.get("active") is False or ch.get("role") or ch.get("unit") else rec.get("pwv", "0")
        _write("users.json", us)
    return public_user(username, rec)


def set_password(username: str, password: str, must_change: bool) -> None:
    _policy_check_password(password)
    with _lock:
        us = users()
        us[username]["pw"] = hash_password(password)
        us[username]["must_change"] = must_change
        us[username]["pwv"] = secrets.token_hex(4)
        _write("users.json", us)


def temp_password() -> str:
    return secrets.token_urlsafe(9)


def bootstrap() -> str | None:
    """Create the top unit and the first administrator when there are none. Password from ENVIROSENSE_ADMIN_PASSWORD, else generated and
    written once to runs/app/auth/first_admin.txt (mode 600); the administrator must change it at first sign-in."""
    with _lock:
        have = bool(users())
    if have:
        return None
    if not units():
        with _lock:
            _write("units.json", {"u_top": {"name": os.environ.get("ENVIROSENSE_TOP_UNIT", "National disaster management authority"),
                                            "parent": None, "created_utc": now(), "created_by": "bootstrap"}})
    pw = os.environ.get("ENVIROSENSE_ADMIN_PASSWORD") or temp_password() + "Aa1"
    create_user(os.environ.get("ENVIROSENSE_ADMIN_USER", "admin"), "System administrator", "admin", next(iter(units())), pw, "bootstrap")
    if not os.environ.get("ENVIROSENSE_ADMIN_PASSWORD"):
        p = DIR / "first_admin.txt"
        p.write_text(f"user: {os.environ.get('ENVIROSENSE_ADMIN_USER', 'admin')}\npassword: {pw}\nChange it at first sign-in, then delete this file.\n")
        os.chmod(p, 0o600)
    return pw


# ---- sessions -------------------------------------------------------------------------------------------------

def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()


def make_token(username: str) -> str:
    rec = users()[username]
    body = base64.urlsafe_b64encode(json.dumps({"u": username, "exp": int(time.time()) + SESSION_HOURS * 3600, "v": rec.get("pwv", "0")}).encode()).decode()
    return f"{body}.{_sign(body)}"


def user_from_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        return None
    rec = users().get(claims.get("u"))
    if not rec or not rec.get("active", True) or claims.get("exp", 0) < time.time() or claims.get("v") != rec.get("pwv", "0"):
        return None
    return {"username": claims["u"], **rec}


def login(username: str, password: str) -> tuple[dict, str]:
    username = (username or "").strip().lower()
    with _lock:
        st = _fails.get(username, {"n": 0, "until": 0})
        if st["until"] > time.time():
            raise AuthError(f"too many failed attempts; try again in {int(st['until'] - time.time()) + 1} s")
    rec = users().get(username)
    ok = bool(rec) and rec.get("active", True) and check_password(password or "", rec["pw"])
    if not rec:
        hash_password("x")  # same cost whether or not the user exists
    with _lock:
        if not ok:
            st["n"] += 1
            if st["n"] >= LOCK_AFTER:
                st = {"n": 0, "until": time.time() + LOCK_SECONDS}
            _fails[username] = st
            raise AuthError("wrong username or password")
        _fails.pop(username, None)
        us = users()
        us[username]["last_login_utc"] = now()
        _write("users.json", us)
    return public_user(username, users()[username]), make_token(username)


# ---- request checks -------------------------------------------------------------------------------------------

def required(method: str, path: str) -> str | None:
    for m, rx, perm in _POLICY:
        if re.fullmatch(m, method) and rx.fullmatch(path):
            return perm
    return None


def current() -> dict | None:
    return _current.get()


def actor() -> str:
    u = current()
    return u["username"] if u else "unknown"


def set_current(user: dict | None):
    _current.set(user)


def can(user: dict, perm: str) -> bool:
    return perm in ("any",) or perm in PERMS.get(user["role"], set())


def visible_units(user: dict) -> set:
    return descendants(user["unit"])


def owners() -> dict:
    return _read("owners.json", {})


def register_owner(key: str, user: dict | None = None) -> None:
    """Record which unit created an upload (the key is the upload id)."""
    user = user or current()
    if user is None:
        return
    with _lock:
        o = owners()
        o[key] = {"unit": user["unit"], "by": user["username"], "utc": now()}
        _write("owners.json", o)


def scope_key(key: str) -> str | None:
    """An upload id (upl_xxxxxxxx) at the start of an upload id or assessment id; None for shared benchmark data."""
    m = re.match(r"upl_[0-9a-f]{8}", key or "")
    return m.group(0) if m else None


def in_scope(key: str, user: dict | None = None) -> bool:
    user = user or current()
    sk = scope_key(key)
    if sk is None:
        return True
    o = owners().get(sk)
    return bool(user and o and o["unit"] in visible_units(user))


def manages(actor_user: dict, unit_id: str) -> bool:
    return unit_id in visible_units(actor_user)


def adopt(key: str, unit: str, by: str = "legacy") -> None:
    """Give an upload made before accounts existed to a unit (the top unit at first start)."""
    with _lock:
        o = owners()
        if key not in o:
            o[key] = {"unit": unit, "by": by, "utc": now()}
            _write("owners.json", o)
