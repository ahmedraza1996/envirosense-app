"""The decision log as rows (gov.decisions): every change of default model, threshold, role, release exception or scope, with its reason and the people
who took it. The database refuses edits and deletions; `markdown` writes the same log as a table for the governance folder or the technical file."""
import json

from ..db.engine import rows, run, tx, using

_STAMP = "YYYY-MM-DD HH24:MI:SS"


def record(kind: str, decision: str, reason: str, decided_by: str, approved_by: str | None = None, ref: str | None = None,
           detail: dict | None = None, c=None) -> None:
    with using(c) as conn:
        run(conn, "INSERT INTO gov.decisions (kind, decision, reason, decided_by, approved_by, ref, detail) VALUES (:k, :d, :r, :b, :a, :ref, CAST(:x AS jsonb))",
            k=kind, d=decision, r=reason, b=decided_by, a=approved_by, ref=ref, x=json.dumps(detail or {}, default=str))


def list_decisions(limit: int = 500) -> list:
    with tx() as c:
        return rows(c, f"SELECT id, to_char(at AT TIME ZONE 'UTC', '{_STAMP}') AS utc, kind, decision, reason, decided_by, approved_by, ref, detail "
                       "FROM gov.decisions ORDER BY at DESC, id DESC LIMIT :n", n=min(max(limit, 1), 5000))


def markdown(limit: int = 5000) -> str:
    out = ["| Date (UTC) | Kind | Decision | Reason | Decided by | Approved by |", "| --- | --- | --- | --- | --- | --- |"]
    for d in reversed(list_decisions(limit)):
        cell = lambda s: (s or "").replace("|", "/").replace("\n", " ")
        out.append(f"| {d['utc'][:10]} | {d['kind']} | {cell(d['decision'])} | {cell(d['reason'])} | {cell(d['decided_by'])} | {cell(d['approved_by'])} |")
    return "\n".join(out) + "\n"
