"""The risk register (gov.risks; it started from governance/risk_register.csv): each risk with its stage, cause, likelihood and severity (1 to 5), the
controls that reduce it, the owner, its status and the date it must be looked at again. Edits need a reason and go to the audit log with the old and new
values; a risk past its review date shows as overdue."""
from ..db.engine import one, rows, run, tx
from . import audit

FIELDS = ("stage", "risk", "cause", "likelihood", "severity", "controls", "planned", "owner", "residual", "status", "next_review")
STATUSES = ("open", "reduced", "accepted", "closed")
_COLS = ("id, stage, risk, cause, likelihood, severity, score, controls, planned, owner, residual, status, to_char(next_review, 'YYYY-MM-DD') AS next_review, "
         "next_review < current_date AS overdue, updated_by, to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') AS updated_utc")


class RiskError(ValueError):
    pass


def list_risks() -> list:
    with tx() as c:
        return rows(c, f"SELECT {_COLS} FROM gov.risks ORDER BY score DESC, id")


def get(rid: str) -> dict:
    with tx() as c:
        r = one(c, f"SELECT {_COLS} FROM gov.risks WHERE id = :i", i=rid)
    if not r:
        raise KeyError(rid)
    return r


def _check(v: dict):
    for k in ("likelihood", "severity"):
        if k in v and not 1 <= int(v[k]) <= 5:
            raise RiskError(f"{k} is 1 to 5")
    if "status" in v and v["status"] not in STATUSES:
        raise RiskError(f"status must be one of {', '.join(STATUSES)}")
    if "controls" in v and not isinstance(v["controls"], list):
        raise RiskError("controls is a list of control ids")


def update(rid: str, changes: dict, by: str, reason: str) -> dict:
    changes = {k: v for k, v in changes.items() if k in FIELDS and v is not None}
    if len((reason or "").strip()) < 10:
        raise RiskError("give the reason for the change (at least 10 characters)")
    _check(changes)
    old = get(rid)
    if not changes:
        return old
    sets = ", ".join(f"{k} = CAST(:{k} AS date)" if k == "next_review" else f"{k} = :{k}" for k in changes)
    with tx() as c:
        run(c, f"UPDATE gov.risks SET {sets}, updated_by = :by, updated_at = now() WHERE id = :i", i=rid, by=by, **changes)
    audit.log("risk_change", by, None, risk=rid, reason=reason.strip(), before={k: old[k] for k in changes}, after=changes)
    return get(rid)


def create(fields: dict, by: str, reason: str) -> dict:
    missing = [k for k in ("stage", "risk", "likelihood", "severity", "owner") if not fields.get(k)]
    if missing:
        raise RiskError(f"missing: {', '.join(missing)}")
    _check(fields)
    with tx() as c:
        n = one(c, "SELECT COALESCE(max(substring(id from 2)::int), 0) + 1 AS n FROM gov.risks")["n"]
        rid = f"R{n:02d}"
        run(c, "INSERT INTO gov.risks (id, stage, risk, cause, likelihood, severity, controls, planned, owner, residual, status, next_review, updated_by) "
               "VALUES (:i, :stage, :risk, :cause, :l, :s, :ctl, :planned, :owner, :residual, :status, COALESCE(CAST(:nr AS date), current_date + 90), :by)",
            i=rid, stage=fields["stage"], risk=fields["risk"], cause=fields.get("cause", ""), l=int(fields["likelihood"]), s=int(fields["severity"]),
            ctl=fields.get("controls") or [], planned=fields.get("planned", ""), owner=fields["owner"], residual=fields.get("residual", ""),
            status=fields.get("status") or "open", nr=fields.get("next_review"), by=by)
    audit.log("risk_added", by, None, risk=rid, reason=(reason or "").strip(), risk_text=fields["risk"])
    return get(rid)
