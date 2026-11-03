"""Users, organisation units, roles and access checks (controls A1-A6 of governance/control_matrix.md).

An organisation is a tree of units (national authority > provincial department > district team). Every user belongs to one unit and has
one role. A user sees and acts on the data of their own unit and the units below it, never on sibling units. Benchmark (xBD) scenes are shared
demonstration data and are visible to every analyst and officer.

Roles
  admin    manages users and units in their unit and below, sets the approved model, reads the audit log; no access to imagery or alerts
  analyst  assesses, uploads, proposes, dismisses, asks for information; cannot confirm, retract or export
  officer  everything an analyst does, plus confirms another person's proposal, retracts, exports, deletes uploads in the unit tree
  auditor  read-only: audit log, review history, policy; no imagery, alert lists or exports

Sessions are rows in iam.sessions; the cookie (HttpOnly) or an `Authorization: Bearer` header carries the session id with an HMAC signature, so
signing out, a password change or deactivating the account ends a session at once. Passwords are stored as scrypt hashes.
Every API route needs a rule in iam.route_policy; a route without one is refused (a test enforces this). Roles, their permissions and the route rules are rows (migration 0003), not code. Accounts, units, sessions and sign-in
throttling live in PostgreSQL (schema iam); it has not been independently security-tested.
"""
import contextvars
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import exc as sa_exc

from ..db.engine import one, rows, run, tx, using
from .engines import ROOT

DIR = ROOT / "runs" / "app" / "auth"
SESSION_HOURS = 12
MIN_PASSWORD = 10
LOCK_AFTER, LOCK_SECONDS = 5, 300
COOKIE = "es_session"
ROLE_TTL = 10.0     # seconds a process keeps the roles and the route policy it read; a change made in this process shows at once


class _Cache:
    """Roles (with their permissions) and the route policy, read from schema iam. Role and route rules are data: see migration 0003."""
    stamp = 0.0
    roles: dict = {}
    policy: list = []
    lock = threading.Lock()


def _load(force: bool = False) -> None:
    if not force and _Cache.roles and time.monotonic() - _Cache.stamp < ROLE_TTL:
        return
    with _Cache.lock, tx() as c:
        roles = {r["key"]: {"label": r["label"], "description": r["description"], "builtin": r["builtin"], "perms": set()}
                 for r in rows(c, "SELECT key, label, description, builtin FROM iam.roles ORDER BY builtin DESC, key")}
        for r in rows(c, "SELECT role_key, permission_key FROM iam.role_permissions"):
            roles[r["role_key"]]["perms"].add(r["permission_key"])
        policy = [(re.compile(r["method"]), re.compile(r["path"]), r["permission"])
                  for r in rows(c, "SELECT method, path, permission FROM iam.route_policy ORDER BY position")]
    _Cache.roles, _Cache.policy, _Cache.stamp = roles, policy, time.monotonic()


def invalidate_roles() -> None:
    _Cache.stamp = 0.0


def role_defs() -> dict:
    _load()
    return _Cache.roles


def perms_of(role: str) -> set:
    return set(role_defs().get(role, {}).get("perms", ()))


class _Perms(Mapping):
    """auth.PERMS[role] -> the permissions of a role (live view of the database)."""
    def __getitem__(self, role):
        if role not in role_defs():
            raise KeyError(role)
        return perms_of(role)
    def __iter__(self): return iter(role_defs())
    def __len__(self): return len(role_defs())


class _Keys:
    """auth.ROLES: the role keys, in a stable order."""
    def __contains__(self, k): return k in role_defs()
    def __iter__(self): return iter(role_defs())


PERMS, ROLES = _Perms(), _Keys()

_current: contextvars.ContextVar = contextvars.ContextVar("current_user", default=None)
_STAMP = "YYYY-MM-DD HH24:MI:SS"
_USER_COLS = (f"u.username, u.full_name AS name, u.role, u.unit_id AS unit, u.pw_hash AS pw, u.active, u.must_change, "
              f"to_char(u.created_at AT TIME ZONE 'UTC', '{_STAMP}') AS created_utc, u.created_by, "
              f"to_char(u.last_login_at AT TIME ZONE 'UTC', '{_STAMP}') AS last_login_utc")
_USER_SQL = f"SELECT {_USER_COLS} FROM iam.users u"


class AuthError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _refused(e: Exception, fallback: str) -> AuthError:
    """A rule held by the database (check, unique or foreign key) became a message the user can read."""
    orig = getattr(e, "orig", None)
    msg = getattr(getattr(orig, "diag", None), "message_primary", None)
    return AuthError(msg if getattr(orig, "sqlstate", "") == "23514" and msg else fallback)


# ---- units ----------------------------------------------------------------------------------------------------

def units() -> dict:
    with tx() as c:
        return {r["id"]: {"name": r["name"], "parent": r["parent"], "created_utc": r["created_utc"], "created_by": r["created_by"]}
                for r in rows(c, f"SELECT id, name, parent_id AS parent, to_char(created_at AT TIME ZONE 'UTC', '{_STAMP}') AS created_utc, "
                                 f"created_by FROM iam.units ORDER BY created_at, id")}


def descendants(unit_id: str, all_units: dict | None = None) -> set:
    if all_units is not None:
        out, todo = {unit_id}, [unit_id]
        while todo:
            cur = todo.pop()
            for k, v in all_units.items():
                if v.get("parent") == cur and k not in out:
                    out.add(k)
                    todo.append(k)
        return out
    with tx() as c:
        return {r["id"] for r in rows(c, "WITH RECURSIVE d AS (SELECT id FROM iam.units WHERE id = :u UNION SELECT x.id FROM iam.units x JOIN d ON x.parent_id = d.id) "
                                         "SELECT id FROM d", u=unit_id)}


def path_names(unit_id: str, _units: dict | None = None) -> str:
    u, parts, seen = _units if _units is not None else units(), [], set()
    while unit_id and unit_id in u and unit_id not in seen:
        seen.add(unit_id)
        parts.append(u[unit_id]["name"])
        unit_id = u[unit_id].get("parent")
    return " > ".join(reversed(parts))


def create_unit(name: str, parent: str | None, by: str) -> dict:
    name = (name or "").strip()
    if not 2 <= len(name) <= 80:
        raise AuthError("a unit name needs 2 to 80 characters")
    uid = "u_" + secrets.token_hex(3)
    try:
        with tx() as c:
            if parent is not None and not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :p", p=parent):
                raise AuthError(f"no parent unit {parent}")
            if parent is None and one(c, "SELECT 1 AS x FROM iam.units LIMIT 1"):
                raise AuthError("there is one top unit; give a parent")
            run(c, "INSERT INTO iam.units (id, name, parent_id, created_by) VALUES (:i, :n, :p, :b)", i=uid, n=name, p=parent, b=by)
    except sa_exc.IntegrityError as e:
        raise AuthError("a unit with that name already exists there") from e
    return {"id": uid, **units()[uid]}


def update_unit(unit_id: str, name: str | None, parent: str | None, move: bool) -> dict:
    if name is not None and not 2 <= len(name.strip()) <= 80:
        raise AuthError("a unit name needs 2 to 80 characters")
    try:
        with tx() as c:
            if not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :u FOR UPDATE", u=unit_id):
                raise KeyError(unit_id)
            if name is not None:
                run(c, "UPDATE iam.units SET name = :n WHERE id = :u", n=name.strip(), u=unit_id)
            if move:
                if not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :p", p=parent):
                    raise AuthError("a unit cannot move under itself or an unknown unit")
                run(c, "UPDATE iam.units SET parent_id = :p WHERE id = :u", p=parent, u=unit_id)
    except sa_exc.IntegrityError as e:
        raise _refused(e, "a unit with that name already exists there") from e
    except sa_exc.InternalError as e:
        raise _refused(e, "that change is not allowed") from e
    return {"id": unit_id, **units()[unit_id]}


# ---- users ----------------------------------------------------------------------------------------------------

def get_user(username: str) -> dict | None:
    with tx() as c:
        return one(c, _USER_SQL + " WHERE u.username = :u", u=username)


def users() -> dict:
    with tx() as c:
        return {r["username"]: r for r in rows(c, _USER_SQL + " ORDER BY u.username")}


def public_user(name: str, rec: dict, _units: dict | None = None) -> dict:
    u = _units if _units is not None else units()
    return {"username": name, "name": rec["name"], "role": rec["role"], "role_label": role_defs()[rec["role"]]["label"], "unit": rec["unit"],
            "unit_name": u.get(rec["unit"], {}).get("name", ""), "unit_path": path_names(rec["unit"], u), "active": rec.get("active", True),
            "must_change_password": rec.get("must_change", False), "created_utc": rec.get("created_utc"),
            "last_login_utc": rec.get("last_login_utc"), "permissions": sorted(perms_of(rec["role"]))}


def list_users(in_units: set | None = None) -> list:
    u = units()
    return [public_user(k, v, u) for k, v in users().items() if in_units is None or v["unit"] in in_units]


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


def create_user(username: str, name: str, role: str, unit: str, password: str, by: str, must_change: bool = True) -> dict:
    username = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
        raise AuthError("a username has 3 to 32 characters: letters, digits, dot, dash, underscore")
    if role not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}")
    if not (name or "").strip():
        raise AuthError("a full name is required")
    _policy_check_password(password)
    try:
        with tx() as c:
            if not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :u", u=unit):
                raise AuthError(f"no unit {unit}")
            run(c, "INSERT INTO iam.users (username, full_name, role, unit_id, pw_hash, must_change, created_by) VALUES (:u, :n, :r, :t, :p, :m, :b)",
                u=username, n=name.strip()[:80], r=role, t=unit, p=hash_password(password), m=must_change, b=by)
    except sa_exc.IntegrityError as e:
        raise AuthError(f"user {username} already exists") from e
    return public_user(username, get_user(username))


def update_user(username: str, **ch) -> dict:
    if ch.get("name") is not None and not ch["name"].strip():
        raise AuthError("a full name is required")
    if ch.get("role") is not None and ch["role"] not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}")
    try:
        with tx() as c:
            rec = one(c, "SELECT username FROM iam.users WHERE username = :u FOR UPDATE", u=username)
            if not rec:
                raise KeyError(username)
            if ch.get("unit") is not None and not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :u", u=ch["unit"]):
                raise AuthError(f"no unit {ch['unit']}")
            sets = {"full_name": ch["name"].strip()[:80] if ch.get("name") is not None else None, "role": ch.get("role"), "unit_id": ch.get("unit"),
                    "active": bool(ch["active"]) if ch.get("active") is not None else None}
            run(c, "UPDATE iam.users SET full_name = COALESCE(:full_name, full_name), role = COALESCE(:role, role), unit_id = COALESCE(:unit_id, unit_id), "
                   "active = COALESCE(:active, active), updated_at = now() WHERE username = :u", u=username, **sets)
            if ch.get("active") is False or ch.get("role") or ch.get("unit"):
                run(c, "UPDATE iam.sessions SET revoked_at = now() WHERE username = :u AND revoked_at IS NULL", u=username)
    except (sa_exc.IntegrityError, sa_exc.InternalError) as e:
        raise _refused(e, "that change is not allowed") from e
    return public_user(username, get_user(username))


def set_password(username: str, password: str, must_change: bool) -> None:
    _policy_check_password(password)
    with tx() as c:
        run(c, "UPDATE iam.users SET pw_hash = :p, must_change = :m, updated_at = now() WHERE username = :u", p=hash_password(password), m=must_change, u=username)
        run(c, "UPDATE iam.sessions SET revoked_at = now() WHERE username = :u AND revoked_at IS NULL", u=username)   # every session ends


def temp_password() -> str:
    return secrets.token_urlsafe(9)


def bootstrap() -> str | None:
    """Create the top unit and the first administrator when there are none. Password from ENVIROSENSE_ADMIN_PASSWORD, else generated and
    written once to runs/app/auth/first_admin.txt (mode 600); the administrator must change it at first sign-in."""
    pw = os.environ.get("ENVIROSENSE_ADMIN_PASSWORD") or temp_password() + "Aa1"
    admin = os.environ.get("ENVIROSENSE_ADMIN_USER", "admin")
    with tx() as c:
        run(c, "SELECT pg_advisory_xact_lock(727002)")           # two processes starting together create one administrator
        if one(c, "SELECT 1 AS x FROM iam.users LIMIT 1"):
            return None
        top = one(c, "SELECT id FROM iam.units WHERE parent_id IS NULL")
        if not top:
            top = {"id": "u_top"}
            run(c, "INSERT INTO iam.units (id, name, created_by) VALUES ('u_top', :n, 'bootstrap')",
                n=os.environ.get("ENVIROSENSE_TOP_UNIT", "National disaster management authority"))
        run(c, "INSERT INTO iam.users (username, full_name, role, unit_id, pw_hash, must_change, created_by) "
               "VALUES (:u, 'System administrator', 'admin', :t, :p, true, 'bootstrap')", u=admin, t=top["id"], p=hash_password(pw))
    if not os.environ.get("ENVIROSENSE_ADMIN_PASSWORD"):
        DIR.mkdir(parents=True, exist_ok=True)
        p = DIR / "first_admin.txt"
        p.write_text(f"user: {admin}\npassword: {pw}\nChange it at first sign-in, then delete this file.\n")
        os.chmod(p, 0o600)
    return pw


# ---- roles, permissions, route policy -------------------------------------------------------------------------

def is_top(user: dict) -> bool:
    """Roles are shared by the whole organisation, so only users of the top unit manage them."""
    return bool(user) and (units().get(user["unit"]) or {}).get("parent") is None


def list_roles() -> list:
    with tx() as c:
        counts = {r["role"]: r["n"] for r in rows(c, "SELECT role, count(*) AS n FROM iam.users GROUP BY role")}
    return [{"key": k, "label": v["label"], "description": v["description"], "builtin": v["builtin"], "permissions": sorted(v["perms"]), "users": counts.get(k, 0)}
            for k, v in role_defs().items()]


def list_permissions() -> dict:
    with tx() as c:
        return {"permissions": rows(c, "SELECT key, description, sensitive FROM iam.permissions WHERE assignable ORDER BY sensitive DESC, key"),
                "conflicts": rows(c, "SELECT a, b, reason FROM iam.permission_conflicts ORDER BY a, b")}


def route_rules() -> list:
    with tx() as c:
        return rows(c, "SELECT position, method, path, permission FROM iam.route_policy ORDER BY position")


def _role_refused(e: Exception, fallback: str) -> AuthError:
    orig = getattr(e, "orig", None)
    diag = getattr(orig, "diag", None)
    msg = getattr(diag, "message_primary", None)
    return AuthError(msg if getattr(orig, "sqlstate", "") in ("23514", "23503") and msg and "violates" not in msg else fallback)


def create_role(key: str, label: str, description: str, permissions: list, by: str) -> dict:
    key = (key or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", key):
        raise AuthError("a role key has 2 to 32 characters: lowercase letters, digits and underscore, starting with a letter")
    if not 2 <= len((label or "").strip()) <= 60:
        raise AuthError("a role name needs 2 to 60 characters")
    try:
        with tx() as c:
            run(c, "INSERT INTO iam.roles (key, label, description, created_by) VALUES (:k, :l, :d, :b)", k=key, l=label.strip(), d=(description or "").strip()[:300], b=by)
            for p in sorted(set(permissions or [])):
                run(c, "INSERT INTO iam.role_permissions (role_key, permission_key) VALUES (:r, :p)", r=key, p=p)
    except sa_exc.IntegrityError as e:
        raise _role_refused(e, f"role {key} already exists or a permission is unknown") from e
    except sa_exc.InternalError as e:
        raise _role_refused(e, "that combination of permissions is not allowed") from e
    invalidate_roles()
    return next(r for r in list_roles() if r["key"] == key)


def set_role_permissions(key: str, permissions: list, c=None) -> dict | None:
    """Replace a custom role's permissions. With `c` the change joins the caller's transaction (nothing is returned until it commits)."""
    perms = sorted(set(permissions or []))
    try:
        with using(c) as conn:
            if not one(conn, "SELECT 1 AS x FROM iam.roles WHERE key = :k FOR UPDATE", k=key):
                raise KeyError(key)
            run(conn, "DELETE FROM iam.role_permissions WHERE role_key = :k", k=key)
            for p in perms:
                run(conn, "INSERT INTO iam.role_permissions (role_key, permission_key) VALUES (:r, :p)", r=key, p=p)
    except sa_exc.IntegrityError as e:
        raise _role_refused(e, "a permission is unknown") from e
    except sa_exc.InternalError as e:
        raise _role_refused(e, "that change is not allowed") from e
    invalidate_roles()
    return next(r for r in list_roles() if r["key"] == key) if c is None else None


def delete_role(key: str) -> None:
    try:
        with tx() as c:
            if not one(c, "SELECT 1 AS x FROM iam.roles WHERE key = :k", k=key):
                raise KeyError(key)
            run(c, "DELETE FROM iam.roles WHERE key = :k", k=key)
    except sa_exc.DBAPIError as e:
        if getattr(e.orig, "sqlstate", "") == "23503":
            raise AuthError("users still hold this role; give them another role first") from e
        raise _role_refused(e, "that role cannot be deleted") from e
    invalidate_roles()


# ---- sessions -------------------------------------------------------------------------------------------------

def _secret() -> bytes:
    env = os.environ.get("ENVIROSENSE_SECRET_KEY")
    if env:
        return bytes.fromhex(env)
    p = DIR / "secret.key"
    if not p.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return p.read_bytes()


def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()


def make_token(username: str, client: str | None = None) -> str:
    """Open a session for the user and return its signed id."""
    with tx() as c:
        sid = one(c, "INSERT INTO iam.sessions (username, expires_at, client) VALUES (:u, now() + make_interval(hours => :h), :c) RETURNING id::text AS id",
                  u=username, h=SESSION_HOURS, c=(client or "")[:120] or None)["id"]
    return f"{sid}.{_sign(sid)}"


def _session_id(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    sid, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(sid)):
        return None
    try:
        return str(uuid.UUID(sid))
    except ValueError:
        return None


def user_from_token(token: str | None) -> dict | None:
    sid = _session_id(token)
    if sid is None:
        return None
    with tx() as c:
        return one(c, f"SELECT {_USER_COLS} FROM iam.users u JOIN iam.sessions s ON s.username = u.username "
                      "WHERE s.id = :s AND s.revoked_at IS NULL AND s.expires_at > now() AND u.active", s=sid)


def end_session(token: str | None) -> None:
    sid = _session_id(token)
    if sid:
        with tx() as c:
            run(c, "UPDATE iam.sessions SET revoked_at = now() WHERE id = :s AND revoked_at IS NULL", s=sid)


def purge_sessions() -> None:
    with tx() as c:
        run(c, "DELETE FROM iam.sessions WHERE expires_at < now() - interval '7 days' OR revoked_at < now() - interval '7 days'")


def login(username: str, password: str, client: str | None = None) -> tuple[dict, str]:
    username = (username or "").strip().lower()
    with tx() as c:
        st = one(c, "SELECT failed_attempts, locked_until, extract(epoch FROM locked_until - now()) AS wait FROM iam.login_throttle WHERE username = :u", u=username)
    if st and st["locked_until"] is not None and st["wait"] > 0:
        raise AuthError(f"too many failed attempts; try again in {int(st['wait']) + 1} s")
    rec = get_user(username)
    ok = bool(rec) and rec["active"] and check_password(password or "", rec["pw"])
    if not rec:
        hash_password("x")  # same cost whether or not the user exists
    with tx() as c:
        if not ok:
            run(c, "INSERT INTO iam.login_throttle (username, failed_attempts) VALUES (:u, 1) "
                   "ON CONFLICT (username) DO UPDATE SET failed_attempts = CASE WHEN iam.login_throttle.failed_attempts + 1 >= :n THEN 0 ELSE iam.login_throttle.failed_attempts + 1 END, "
                   "locked_until = CASE WHEN iam.login_throttle.failed_attempts + 1 >= :n THEN now() + make_interval(secs => :s) ELSE NULL END",
                u=username, n=LOCK_AFTER, s=LOCK_SECONDS)
        else:
            run(c, "DELETE FROM iam.login_throttle WHERE username = :u", u=username)
            run(c, "UPDATE iam.users SET last_login_at = now() WHERE username = :u", u=username)
    if not ok:
        raise AuthError("wrong username or password")
    return public_user(username, get_user(username)), make_token(username, client)


# ---- request checks -------------------------------------------------------------------------------------------

def required(method: str, path: str) -> str | None:
    _load()
    for m, rx, perm in _Cache.policy:
        if m.fullmatch(method) and rx.fullmatch(path):
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
    return perm == "any" or perm in perms_of(user["role"])


def visible_units(user: dict) -> set:
    return descendants(user["unit"])


def scope_key(key: str) -> str | None:
    """An upload id (upl_xxxxxxxx) at the start of an upload id or assessment id; None for shared benchmark data."""
    m = re.match(r"upl_[0-9a-f]{8}", key or "")
    return m.group(0) if m else None


def owner_of(upload_id: str) -> dict | None:
    with tx() as c:
        return one(c, "SELECT unit_id AS unit, created_by AS by FROM ingest.uploads WHERE id = :i", i=upload_id)


def in_scope(key: str, user: dict | None = None) -> bool:
    user = user or current()
    sk = scope_key(key)
    if sk is None:
        return True
    o = owner_of(sk)
    return bool(user and o and o["unit"] in visible_units(user))


def manages(actor_user: dict, unit_id: str) -> bool:
    return unit_id in visible_units(actor_user)
