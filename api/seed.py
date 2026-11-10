"""Demo accounts: a fixed organisation of four units and one or two accounts per role, all with one known password, written to the
database at every start so a demonstration always begins from the same sign-ins.

On by default for development. Set ENVIROSENSE_DEMO_ACCOUNTS=0 on a real deployment: the accounts are then left alone (not created, not
reset) and the sign-in page no longer lists them. The password is ENVIROSENSE_DEMO_PASSWORD, default abc12345. It is stored like any
other password, as a scrypt hash; the plain value lives only in this setting.
"""
import os

from ..db.engine import one, run, tx
from . import auth

PASSWORD = os.environ.get("ENVIROSENSE_DEMO_PASSWORD", "abc12345")

#        key        id fallback   name                                      parent
UNITS = [("top", "u_top", "National disaster management authority", None),
         ("punjab", "u_punjab", "Punjab provincial disaster management", "top"),
         ("sindh", "u_sindh", "Sindh provincial disaster management", "top"),
         ("karachi", "u_karachi", "Karachi district team", "sindh")]

#         username            full name                     role       unit
USERS = [("admin", "System administrator", "admin", "top"),
         ("nda.admin", "National administrator", "admin", "top"),
         ("nda.officer", "National approving officer", "officer", "top"),
         ("punjab.officer", "Punjab approving officer", "officer", "punjab"),
         ("sindh.officer", "Sindh approving officer", "officer", "sindh"),
         ("karachi.analyst1", "Karachi analyst one", "analyst", "karachi"),
         ("karachi.analyst2", "Karachi analyst two", "analyst", "karachi"),
         ("nda.auditor", "National auditor", "auditor", "top")]


def enabled() -> bool:
    return os.environ.get("ENVIROSENSE_DEMO_ACCOUNTS", "1") != "0"


def ensure() -> list[str]:
    """Create the demo units and accounts if missing, and put each account back to its demo role, unit and password (active, no forced
    change, no lock-out). Units are matched by name under their parent, so existing ones keep their ids. Returns the accounts changed."""
    if not enabled():
        return []
    changed = []
    with tx() as c:
        run(c, "SELECT pg_advisory_xact_lock(727003)")       # two processes starting together seed once
        ids = {}
        for key, fallback, name, parent in UNITS:
            pid = ids.get(parent)
            r = one(c, "SELECT id FROM iam.units WHERE parent_id IS NULL") if parent is None else \
                one(c, "SELECT id FROM iam.units WHERE parent_id = :p AND lower(btrim(name)) = lower(:n)", p=pid, n=name)
            if not r:
                run(c, "INSERT INTO iam.units (id, name, parent_id, created_by) VALUES (:i, :n, :p, 'demo seed')", i=fallback, n=name, p=pid)
                r = {"id": fallback}
            ids[key] = r["id"]
        for username, name, role, unit in USERS:
            cur = one(c, "SELECT full_name, role, unit_id, pw_hash, active, must_change FROM iam.users WHERE username = :u", u=username)
            if cur and (cur["full_name"], cur["role"], cur["unit_id"], cur["active"], cur["must_change"]) == (name, role, ids[unit], True, False) \
                    and auth.check_password(PASSWORD, cur["pw_hash"]):
                continue
            pw = auth.hash_password(PASSWORD)
            if cur:
                run(c, "UPDATE iam.users SET full_name = :n, role = :r, unit_id = :t, pw_hash = :p, active = true, must_change = false, updated_at = now() "
                       "WHERE username = :u", u=username, n=name, r=role, t=ids[unit], p=pw)
            else:
                run(c, "INSERT INTO iam.users (username, full_name, role, unit_id, pw_hash, must_change, created_by) VALUES (:u, :n, :r, :t, :p, false, 'demo seed')",
                    u=username, n=name, r=role, t=ids[unit], p=pw)
            run(c, "DELETE FROM iam.login_throttle WHERE username = :u", u=username)
            changed.append(username)
    if changed:
        from . import audit
        audit.log("demo_accounts_seeded", "system (startup)", None, accounts=changed)
        auth.invalidate_roles()
    return changed


def listing() -> dict | None:
    """What the sign-in page shows in demo mode: the accounts by role, and the shared password."""
    if not enabled():
        return None
    labels = {r["key"]: r["label"] for r in auth.list_roles()}
    return {"password": PASSWORD,
            "accounts": [{"username": u, "name": n, "role": r, "role_label": labels.get(r, r.title()), "unit": t.title() if t != "top" else "National"}
                         for u, n, r, t in USERS]}
