"""The incident register (gov.incidents, gov.incident_events): something went wrong, or may have.

Raised by a person (anyone signed in) or by a check (a retracted alert, live accuracy under its floor, drift in the uploads, a broken audit chain). An
incident is open, then investigating, then closed with its cause and resolution; a closed incident changes only by being reopened, and nothing is ever
deleted (the database holds both rules). A check raises at most one open incident per problem (dedup key), adding a note when it sees it again.
A serious incident must reach the supervisor within 24 hours (governance/incident_procedure.md).
"""
import json

from sqlalchemy import exc as sa_exc

from ..db.engine import one, rows, run, tx
from . import audit, auth

KINDS = ("wrong_alert", "model_quality", "data_drift", "security", "audit_chain", "access", "other")
SEVERITIES = ("low", "medium", "high", "serious")
_STAMP = "YYYY-MM-DD HH24:MI:SS"
SERIOUS_NOTE = "Serious incident: report to the supervisor within 24 hours and stop using the affected output until it is closed."


class IncidentError(ValueError):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _event(c, iid: int, actor: str, action: str, note: str = "", **detail):
    run(c, "INSERT INTO gov.incident_events (incident_id, actor, action, note, detail) VALUES (:i, :a, :x, :n, CAST(:d AS jsonb))",
        i=iid, a=actor, x=action, n=note, d=json.dumps(detail, default=str))


def open_incident(kind: str, severity: str, title: str, description: str, actor: str, source: str = "person", unit: str | None = None,
                  links: dict | None = None, dedup_key: str | None = None) -> dict:
    """Open an incident. With a dedup key and one already open for it, adds a note to that one instead and returns it."""
    if kind not in KINDS:
        raise IncidentError(f"kind must be one of {', '.join(KINDS)}")
    if severity not in SEVERITIES:
        raise IncidentError(f"severity must be one of {', '.join(SEVERITIES)}")
    title, description = (title or "").strip(), (description or "").strip()
    if len(title) < 5:
        raise IncidentError("give a title (at least 5 characters)")
    if severity == "serious" and SERIOUS_NOTE not in description:
        description = (description + "\n\n" if description else "") + SERIOUS_NOTE
    if dedup_key:
        with tx() as c:
            hit = one(c, "SELECT id FROM gov.incidents WHERE dedup_key = :k AND state <> 'closed'", k=dedup_key)
            if hit:
                _event(c, hit["id"], actor, "note", "Seen again: " + title)
                return get(hit["id"])
    try:
        with tx() as c:
            iid = one(c, "INSERT INTO gov.incidents (kind, severity, title, description, source, dedup_key, opened_by, unit_id, links) "
                         "VALUES (:k, :s, :t, :d, :src, :key, :by, :u, CAST(:l AS jsonb)) RETURNING id",
                      k=kind, s=severity, t=title[:160], d=description, src=source, key=dedup_key, by=actor, u=unit, l=json.dumps(links or {}))["id"]
            _event(c, iid, actor, "opened", description)
    except sa_exc.IntegrityError:                          # the same check ran twice at once: the other one opened it
        with tx() as c:
            return get(one(c, "SELECT id FROM gov.incidents WHERE dedup_key = :k AND state <> 'closed'", k=dedup_key)["id"])
    audit.log("incident_opened", actor, (links or {}).get("assessment"), incident=iid, kind=kind, severity=severity, title=title, source=source)
    return get(iid)


def _visible(user: dict | None):
    """Incidents a user may see: their unit tree's, and those raised by checks (no unit)."""
    return None if user is None else sorted(auth.visible_units(user))


def get(iid: int, user: dict | None = None) -> dict:
    vis = _visible(user)
    with tx() as c:
        r = one(c, f"SELECT id, kind, severity, title, description, source, state, opened_by, unit_id, links, cause, resolution, closed_by, "
                   f"to_char(opened_at AT TIME ZONE 'UTC', '{_STAMP}') AS opened_utc, to_char(closed_at AT TIME ZONE 'UTC', '{_STAMP}') AS closed_utc "
                   f"FROM gov.incidents WHERE id = :i AND (CAST(:v AS text[]) IS NULL OR unit_id IS NULL OR unit_id = ANY(:v))", i=iid, v=vis)
        if not r:
            raise KeyError(iid)
        r["events"] = rows(c, f"SELECT actor, action, note, detail, to_char(at AT TIME ZONE 'UTC', '{_STAMP}') AS utc FROM gov.incident_events "
                              f"WHERE incident_id = :i ORDER BY id", i=iid)
    return r


def list_incidents(user: dict | None = None, state: str | None = None, limit: int = 200) -> list:
    with tx() as c:
        return rows(c, f"SELECT id, kind, severity, title, source, state, opened_by, unit_id, links, "
                       f"to_char(opened_at AT TIME ZONE 'UTC', '{_STAMP}') AS opened_utc, to_char(closed_at AT TIME ZONE 'UTC', '{_STAMP}') AS closed_utc "
                       f"FROM gov.incidents WHERE (CAST(:s AS text) IS NULL OR state = :s) AND (CAST(:v AS text[]) IS NULL OR unit_id IS NULL OR unit_id = ANY(:v)) "
                       f"ORDER BY state = 'closed', CASE severity WHEN 'serious' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, opened_at DESC LIMIT :n",
                    s=state, v=_visible(user), n=min(max(limit, 1), 1000))


def _change(iid: int, user: dict, action: str, sql: str, note: str, **p) -> dict:
    get(iid, user)                                         # scope: 404 outside the user's unit tree
    with tx() as c:
        cur = one(c, "SELECT state FROM gov.incidents WHERE id = :i FOR UPDATE", i=iid)
        allowed = {"assessed": ("open", "investigating"), "note": ("open", "investigating"), "closed": ("open", "investigating"), "reopened": ("closed",)}[action]
        if cur["state"] not in allowed:
            raise IncidentError(f"this incident is {cur['state']}", 409)
        if sql:
            run(c, sql, i=iid, **p)
        _event(c, iid, user["username"], action, note, **{k: v for k, v in p.items() if k in ("severity", "cause", "resolution")})
    audit.log(f"incident_{action}", user["username"], None, incident=iid, note=note, **{k: v for k, v in p.items() if k in ("severity", "cause")})
    return get(iid, user)


def assess(iid: int, user: dict, note: str, severity: str | None = None) -> dict:
    if len((note or "").strip()) < 5:
        raise IncidentError("say what was found or done (at least 5 characters)")
    if severity and severity not in SEVERITIES:
        raise IncidentError(f"severity must be one of {', '.join(SEVERITIES)}")
    return _change(iid, user, "assessed", "UPDATE gov.incidents SET state = 'investigating', severity = COALESCE(CAST(:severity AS text), severity) WHERE id = :i",
                   note.strip(), severity=severity)


def add_note(iid: int, user: dict, note: str) -> dict:
    if len((note or "").strip()) < 3:
        raise IncidentError("write a note")
    return _change(iid, user, "note", "", note.strip())


def close(iid: int, user: dict, cause: str, resolution: str) -> dict:
    cause, resolution = (cause or "").strip(), (resolution or "").strip()
    if len(cause) < 5 or len(resolution) < 10:
        raise IncidentError("give the cause (at least 5 characters) and what was done about it (at least 10)")
    return _change(iid, user, "closed", "UPDATE gov.incidents SET state = 'closed', closed_by = :by, closed_at = now(), cause = :cause, resolution = :resolution "
                                        "WHERE id = :i", f"Cause: {cause}. Resolution: {resolution}", by=user["username"], cause=cause, resolution=resolution)


def reopen(iid: int, user: dict, note: str) -> dict:
    if len((note or "").strip()) < 5:
        raise IncidentError("say why it is reopened (at least 5 characters)")
    return _change(iid, user, "reopened", "UPDATE gov.incidents SET state = 'open', closed_by = NULL, closed_at = NULL WHERE id = :i", note.strip())


def counts() -> dict:
    with tx() as c:
        r = one(c, "SELECT count(*) FILTER (WHERE state <> 'closed') AS open, count(*) FILTER (WHERE state <> 'closed' AND severity IN ('high', 'serious')) AS urgent, "
                   "count(*) AS total FROM gov.incidents")
    return r
