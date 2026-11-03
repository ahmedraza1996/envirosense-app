"""Incident candidates from the records (control I1, governance/incident_procedure.md).

Lists, from the audit log and the review history in the database: retracted alerts, denied actions, failed sign-ins and anything unusual about the chain. It decides
nothing; a person reads the list and writes the incident log.
"""
from ..db.engine import rows as query
from ..db.engine import tx
from . import audit


def collect(limit: int = 100000) -> dict:
    entries = audit.read(None, limit)
    with tx() as c:
        retractions = [{"assessment": r["assessment_id"], "alert_id": r["alert_id"], "by": r["actor"], "utc": r["utc"], "reason": r["note"]}
                       for r in query(c, "SELECT assessment_id, alert_id, actor, note, to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS utc "
                                         "FROM wf.alert_review_events WHERE status = 'retracted' ORDER BY at, id")]
    denied = [r for r in entries if r["action"] == "denied"]
    failed = [r for r in entries if r["action"] == "login_failed"]
    by_user: dict = {}
    for r in failed:
        by_user[r["detail"].get("username") or r["actor"]] = by_user.get(r["detail"].get("username") or r["actor"], 0) + 1
    return {"chain": audit.verify(), "retractions": retractions, "denied": denied, "failed_sign_ins": failed,
            "failed_by_user": dict(sorted(by_user.items(), key=lambda kv: -kv[1])),
            "model_approvals": [r for r in entries if r["action"] == "model_approval"]}


def markdown(c: dict) -> str:
    ch = c["chain"]
    out = ["# Incident candidates from the records", "",
           f"Audit chain: {'intact' if ch['ok'] else 'BROKEN at line ' + str(ch['first_bad_line'])}, {ch['entries']} entries.", "",
           f"## Retracted alerts ({len(c['retractions'])})"]
    out += [f"- {r['utc']} UTC, {r['by']}: {r['assessment']} / {r['alert_id']}: {r['reason']}" for r in c["retractions"]] or ["- none"]
    out += ["", f"## Denied actions ({len(c['denied'])})"]
    out += [f"- {r['utc']} UTC, {r['actor']}: {r['detail'].get('method', '')} {r['detail'].get('path', r['assessment'] or '')} "
            f"(needed {r['detail'].get('needed', r['detail'].get('why', ''))})" for r in c["denied"]] or ["- none"]
    out += ["", f"## Failed sign-ins ({len(c['failed_sign_ins'])})"]
    out += [f"- {u}: {n}" for u, n in c["failed_by_user"].items()] or ["- none"]
    out += ["", f"## Default-model approvals ({len(c['model_approvals'])})"]
    out += [f"- {r['utc']} UTC, {r['actor']}: {r['detail'].get('previous')} to {r['detail'].get('model')}: {r['detail'].get('reason')}" for r in c["model_approvals"]] or ["- none"]
    return "\n".join(out) + "\n"
