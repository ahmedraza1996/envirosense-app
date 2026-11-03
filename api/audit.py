"""Append-only audit log with a hash chain (control X1 of governance/control_matrix.md).

One row per action that changes something or releases something: assessment, review, retraction, export, map offset, upload, delete, model
approval, sign-in. Each row carries the hash of the previous row, so a removed or edited row breaks the chain and `verify` says where. It
records who did it (the signed-in account, with its unit and role), when, to which assessment, and the versions involved.

The table is in PostgreSQL (audit.log). The running application's role may only insert and select; the database refuses updates, deletes and
truncation by anyone, and refuses a row that does not follow the last one, so an application bug cannot break the chain either. Whoever
administers the database server can still rewrite everything: for that the chain head is meant to be kept elsewhere (see docs/operations.md).
"""
import hashlib
import json
from datetime import datetime, timezone

import sqlalchemy as sa

from ..db.engine import one, rows, run, tx
from . import auth

GENESIS = "0" * 64
_STAMP = "%Y-%m-%d %H:%M:%S"


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def log(action: str, actor: str | None, assessment: str | None = None, **detail) -> dict:
    u = auth.current()
    if u:                                   # who, from which unit and in which role: for scoping what an administrator or auditor sees
        detail.setdefault("actor_unit", u["unit"])
        detail.setdefault("actor_role", u["role"])
    detail = json.loads(json.dumps(detail, default=str))   # what is stored is what is hashed
    with tx() as c:
        run(c, "SELECT pg_advisory_xact_lock(727001)")     # one writer at a time: the chain is a single line
        last = one(c, "SELECT seq, hash FROM audit.log ORDER BY seq DESC LIMIT 1")
        seq, prev = (last["seq"], last["hash"].strip()) if last else (0, GENESIS)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = {"seq": seq + 1, "utc": now.strftime(_STAMP), "action": action, "actor": (actor or "").strip() or "unknown",
                 "assessment": assessment, "detail": detail, "prev": prev}
        entry["hash"] = _digest(entry)
        run(c, "INSERT INTO audit.log (seq, utc, action, actor, assessment, detail, actor_unit, actor_role, prev, hash) "
               "VALUES (:seq, :utc, :action, :actor, :assessment, CAST(:detail AS json), :unit, :role, :prev, :hash)",
            seq=entry["seq"], utc=now, action=action, actor=entry["actor"], assessment=assessment, detail=json.dumps(detail, ensure_ascii=False),
            unit=detail.get("actor_unit"), role=detail.get("actor_role"), prev=prev, hash=entry["hash"])
    return entry


def _entry(r: dict) -> dict:
    return {"seq": r["seq"], "utc": r["utc"].astimezone(timezone.utc).strftime(_STAMP), "action": r["action"], "actor": r["actor"],
            "assessment": r["assessment"], "detail": r["detail"] if isinstance(r["detail"], dict) else json.loads(r["detail"]), "prev": r["prev"].strip(), "hash": r["hash"].strip()}


def read(assessment: str | None = None, limit: int = 200, units: set | None = None, include_unscoped: bool = False) -> list:
    """The newest `limit` entries, oldest first. `units` limits them to actors in those units (and, with include_unscoped, to entries
    that carry no unit: those from before accounts existed)."""
    where, p = [], {"n": limit}
    if assessment:
        where.append("assessment = :a")
        p["a"] = assessment
    if units is not None:
        where.append("(actor_unit = ANY(:u)" + (" OR actor_unit IS NULL" if include_unscoped else "") + ")")
        p["u"] = sorted(units)
    sql = "SELECT * FROM audit.log " + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY seq DESC LIMIT :n"
    with tx() as c:
        return [_entry(r) for r in reversed(rows(c, sql, **p))]


def verify() -> dict:
    """Walk the chain in order. ok is False at the first entry whose hash or link does not match."""
    prev, n = GENESIS, 0
    with tx() as c:
        for r in c.execution_options(stream_results=True, yield_per=500).execute(sa.text("SELECT * FROM audit.log ORDER BY seq")).mappings():
            e = _entry(dict(r))
            if e["prev"] != prev or e["hash"] != _digest(e) or e["seq"] != n + 1:
                return {"ok": False, "entries": n, "first_bad_line": n + 1, "reason": "hash chain broken"}
            prev, n = e["hash"], n + 1
    return {"ok": True, "entries": n, "first_bad_line": None, "reason": ""}
