"""One-time import of the data the app kept in files before it used PostgreSQL.

  uv run --no-sync python -m app.scripts.db_import_files            # shows what would be imported
  uv run --no-sync python -m app.scripts.db_import_files --apply    # imports it

Imports, in this order: units, users (with their password hashes), model versions (and the approved default from governance/approved_model.json),
uploads and their last job, assessments and alerts from the stored records, review decisions with their history, and the audit log
entry by entry, so the hash chain carries over unchanged and `verify` still passes. It is safe to run again: what already exists is skipped,
and the audit log is only imported while it is empty. The files are left where they are; archive them yourself once the import is checked.
"""
import json
import sys
from pathlib import Path

from app.api import audit, auth, engines, registry, service, uploads
from app.db import semantic
from app.db.engine import one, rows, run, tx

RUNS = engines.ROOT / "runs" / "app"


def load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def ts(s):
    return (s + "+00") if s and len(s) == 19 else s


def main(apply: bool) -> int:
    out = {"units": 0, "users": 0, "uploads": 0, "assessments": 0, "alerts": 0, "reviews": 0, "review_events": 0, "audit": 0}
    warn = []
    units = load(RUNS / "auth" / "units.json", {})
    users = load(RUNS / "auth" / "users.json", {})
    owners = load(RUNS / "auth" / "owners.json", {})
    top = next((k for k, v in units.items() if v.get("parent") is None), None)
    say = lambda *a: print(*a, flush=True)
    say(f"files: {len(units)} units, {len(users)} users, {len(owners)} upload owners, "
        f"{len(list((RUNS / 'uploads').glob('upl_*/meta.json')))} uploads, {len(list((RUNS / 'assessments').glob('*__area.json')))} area records, "
        f"{len(list((RUNS / 'reviews').glob('*.json')))} review files, {sum(1 for _ in (RUNS / 'audit' / 'audit.jsonl').open()) if (RUNS / 'audit' / 'audit.jsonl').exists() else 0} audit entries")
    if not apply:
        say("dry run: nothing written. Run with --apply to import.")
        return 0

    with tx() as c:
        done, todo = set(), dict(units)
        while todo:
            ready = [k for k, v in todo.items() if v.get("parent") in (None, *done)]
            if not ready:
                warn.append(f"units with an unknown parent skipped: {sorted(todo)}")
                break
            for k in ready:
                v = todo.pop(k)
                if not one(c, "SELECT 1 AS x FROM iam.units WHERE id = :i", i=k):
                    run(c, "INSERT INTO iam.units (id, name, parent_id, created_at, created_by) VALUES (:i, :n, :p, CAST(:t AS timestamptz), :b)",
                        i=k, n=v["name"], p=v.get("parent"), t=ts(v.get("created_utc")), b=v.get("created_by") or "import")
                    out["units"] += 1
                done.add(k)
        for name, v in users.items():
            if not one(c, "SELECT 1 AS x FROM iam.users WHERE username = :u", u=name):
                run(c, "INSERT INTO iam.users (username, full_name, role, unit_id, pw_hash, active, must_change, last_login_at, created_at, created_by) "
                       "VALUES (:u, :n, :r, :t, :p, :a, :m, CAST(:l AS timestamptz), CAST(:c AS timestamptz), :b)",
                    u=name, n=v["name"], r=v["role"], t=v["unit"], p=v["pw"], a=v.get("active", True), m=v.get("must_change", False),
                    l=ts(v.get("last_login_utc")), c=ts(v.get("created_utc")), b=v.get("created_by") or "import")
                out["users"] += 1

    semantic.sync_models(service.models(), engines.APPROVED)

    for d in sorted((RUNS / "uploads").glob("upl_*")):
        meta = load(d / "meta.json", None)
        if meta is None:
            continue
        if one_exists("ingest.uploads", d.name):
            continue
        own = owners.get(d.name) or {"unit": top, "by": "legacy"}
        st = load(d / "status.json", {})
        uploads.register(d.name, {**meta, "after_file": meta["after_file"]}, own["unit"], own["by"], queue=False)
        state = {"done": "succeeded", "failed": "failed"}.get(st.get("state"), "failed")
        err = st.get("error") or (None if state == "succeeded" else "interrupted before the import; upload again")
        with tx() as c:
            run(c, "INSERT INTO ingest.jobs (upload_id, state, step, attempts, error, error_detail, result, finished_at, created_by, created_at) "
                   "VALUES (:u, :s, :p, 1, :e, :t, CAST(:r AS jsonb), CAST(:f AS timestamptz), :b, COALESCE(CAST(:cr AS timestamptz), now()))",
                u=d.name, s=state, p=st.get("step") or "", e=err, t=st.get("trace"), b=own["by"], cr=ts(meta.get("created_utc")), f=ts(st.get("updated_utc")),
                r=json.dumps({k: st[k] for k in ("assessment_id", "alerts") if k in st}))
        out["uploads"] += 1

    for f in sorted((RUNS / "assessments").glob("*__area.json")):
        try:
            rec = json.loads(f.read_text())
            registry.register(rec, f)
            out["assessments"] += 1
            out["alerts"] += len(rec.get("alerts") or [])
        except Exception as e:  # noqa: BLE001  report and carry on: one odd record must not stop the import
            warn.append(f"{f.name}: {type(e).__name__}: {str(e)[:120]}")

    for f in sorted((RUNS / "reviews").glob("*.json")):
        aid = f.stem
        for alert_id, e in (load(f, {}).get("alerts") or {}).items():
            try:
                with tx() as c:
                    run(c, "INSERT INTO wf.alert_reviews (assessment_id, alert_id, status, note, reviewed_by, reviewed_at, proposed_by) "
                           "VALUES (:a, :i, :s, :n, :b, CAST(:t AS timestamptz), :p) ON CONFLICT DO NOTHING",
                        a=aid, i=alert_id, s=e["status"], n=e.get("note") or "", b=e.get("reviewed_by"), t=ts(e.get("reviewed_utc")), p=e.get("proposed_by"))
                    for n, h in enumerate(e.get("history") or [], 1):
                        run(c, "INSERT INTO wf.alert_review_events (assessment_id, alert_id, seq, status, note, actor, role, unit_id, at) "
                               "VALUES (:a, :i, :n, :s, :t, :b, :r, :u, CAST(:at AS timestamptz)) ON CONFLICT DO NOTHING",
                            a=aid, i=alert_id, n=n, s=h["status"], t=h.get("note") or "", b=h["by"], r=h.get("role") or "analyst", u=h.get("unit"), at=ts(h["utc"]))
                        out["review_events"] += 1
                out["reviews"] += 1
            except Exception as ex:  # noqa: BLE001
                warn.append(f"review {aid}/{alert_id} not imported: {str(ex)[:140]}")

    with tx() as c:
        empty = not one(c, "SELECT 1 AS x FROM audit.log LIMIT 1")
    if empty and (RUNS / "audit" / "audit.jsonl").exists():
        with tx() as c:
            run(c, "SELECT pg_advisory_xact_lock(727001)")
            for line in (RUNS / "audit" / "audit.jsonl").read_text().splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                d = e.get("detail") or {}
                run(c, "INSERT INTO audit.log (seq, utc, action, actor, assessment, detail, actor_unit, actor_role, prev, hash) "
                       "VALUES (:s, CAST(:u AS timestamptz), :a, :ac, :as_, CAST(:d AS json), :un, :ro, :p, :h)",
                    s=e["seq"], u=ts(e["utc"]), a=e["action"], ac=e["actor"], as_=e.get("assessment"), d=json.dumps(d, ensure_ascii=False),
                    un=d.get("actor_unit"), ro=d.get("actor_role"), p=e["prev"], h=e["hash"])
                out["audit"] += 1
    v = audit.verify()
    say("imported:", out)
    say("audit chain after import:", v)
    for w in warn:
        say("WARNING:", w)
    return 0 if v["ok"] else 1


def one_exists(table: str, key: str) -> bool:
    with tx() as c:
        return bool(one(c, f"SELECT 1 AS x FROM {table} WHERE id = :k", k=key))


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
