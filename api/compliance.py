"""Compliance: the control register (governance/controls.json) checked against its evidence, and each framework scored from it.

A control is a check with a rule and an owner. Its evidence is one or more of:
  test           a test in tests/ that proves the rule; its last result comes from runs/app/test_results.json (written by every test run)
  live           a check run now against the database and the files (the audit chain verifies, the approved model's file matches its hash ...)
  file           a document that must exist
  file_contains  a piece of code or text that must be present
  record         a dated record of a procedure (governance/records/<name>_YYYY-MM-DD.md) not older than its interval
A control is met when all its evidence holds, partly met when some does, not met when none does. A framework requirement (governance/frameworks.json)
is met when every control tagged with it is met. The technical file is produced from the same records, so it cannot drift from them.
"""
import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from ..db import semantic
from ..db.engine import one, rows, run, tx
from . import audit, decisions, model_registry, monitoring, risks, seed, service, uploads
from .engines import ROOT

APP = Path(__file__).resolve().parents[1]
GOV = APP / "governance"
TEST_RESULTS = ROOT / "runs" / "app" / "test_results.json"
OK, FAIL, UNKNOWN = "ok", "fail", "not measured"


def controls() -> dict:
    return json.loads((GOV / "controls.json").read_text())


def frameworks() -> dict:
    return json.loads((GOV / "frameworks.json").read_text())


# ---- live checks: each returns (status, what was found) --------------------------------------------------------------

def _approved():
    mid = semantic.approved_id()
    m = service.models().get(mid) if mid else None
    return mid, m


def _evidence_of_approved():
    mid, m = _approved()
    if not m:
        return None
    return model_registry._card_module().evidence(Path(m["run_dir"]))


def _audit_chain():
    v = audit.verify()
    return (OK, f"{v['entries']} entries verified") if v["ok"] else (FAIL, f"broken at entry {v['first_bad_line']}")


def _approved_model_hash():
    mid, m = _approved()
    if not m:
        return FAIL, "no approved model is available on this server"
    rec = next((v for v in semantic.model_versions() if v["id"] == mid), {})
    now = semantic.file_sha256(Path(m["run_dir"]) / "best.pt")
    return (OK, f"{mid}: checkpoint matches {now[:12]}…") if rec.get("checkpoint_sha256") == now else (FAIL, f"{mid}: the checkpoint differs from its recorded hash")


def _approved_model_gate():
    mid, m = _approved()
    if not m:
        return FAIL, "no approved model"
    sc = model_registry.scorecard(mid)
    if sc["gate_open"]:
        return OK, f"{mid} passes all {sc['passed']} criteria"
    return FAIL, f"{mid}: {sc['passed']} passed, missed {', '.join(sc['failed']) or 'none'}, not measured {', '.join(sc['missing']) or 'none'}"


def _derived(metric, ok_text, missing_text):
    ev = _evidence_of_approved()
    if ev is None:
        return FAIL, "no approved model"
    v = ev["derived"].get(metric)
    return (OK, ok_text.format(v=v)) if v not in (None, False) else (FAIL, missing_text)


def _approved_run_record():
    ev = _evidence_of_approved()
    if ev is None:
        return FAIL, "no approved model"
    missing = [k for k in ("git_commit", "splits_sha256", "seed", "command") if ev["config"].get(k) in (None, "")]
    return (OK, "code version, data-split hash, seed and command recorded") if not missing else (FAIL, "not recorded: " + ", ".join(missing))


def _approved_model_card():
    return _derived("record.card", "model card saved with the run", "the run has no saved model card (only a draft generated now)")


def _seeds_measured():
    return _derived("seeds.hold_mean", "hold mean over three seeds {v}", "single training run: no seed repeats")


def _unseen_measured():
    return _derived("unseen.mean", "mean on unseen disasters {v}", "not scored on disasters left out of training")


def _robustness_measured():
    ev = _evidence_of_approved()
    if ev is None:
        return FAIL, "no approved model"
    have = [n for n, x in (("robustness", ev["robustness"]), ("calibration", ev["calibration"])) if x]
    return (OK, "robustness and calibration measured") if len(have) == 2 else (FAIL, "missing: " + ", ".join({"robustness", "calibration"} - set(have)))


def _previous_model_available():
    prev = semantic.approved_model().get("previous")
    if not prev:
        return FAIL, "no previous approved model recorded"
    return (OK, f"{prev} can be approved again") if prev in service.models() else (FAIL, f"{prev} is not available on this server")


def _licence_recorded():
    text = (GOV / "datasheet_xbd.md").read_text() if (GOV / "datasheet_xbd.md").exists() else ""
    return (FAIL, "the datasheet still says [to confirm]") if "[to confirm]" in text or not text else (OK, "licence recorded in the datasheet")


def _leakage_free():
    path = ROOT / "configs" / "pair_splits.csv"
    if not path.exists():
        return UNKNOWN, "configs/pair_splits.csv not found"
    seen: dict = {}
    for r in csv.DictReader(path.open()):
        seen.setdefault(r["pair_id"], set()).add(r["official_split"])
    twice = [p for p, s in seen.items() if len(s) > 1]
    return (OK, f"{len(seen)} pairs, each in one split") if not twice else (FAIL, f"{len(twice)} pairs in more than one split")


def _uploads_have_rights():
    with tx() as c:
        r = one(c, "SELECT count(*) AS n, count(*) FILTER (WHERE source IS NOT NULL AND licence IS NOT NULL AND rights_confirmed_by IS NOT NULL) AS ok "
                   "FROM ingest.uploads WHERE created_at > now() - interval '90 days'")
    if not r["n"]:
        return UNKNOWN, "no uploads in the last 90 days"
    return (OK, f"all {r['n']} recent uploads") if r["ok"] == r["n"] else (FAIL, f"{r['n'] - r['ok']} of {r['n']} recent uploads have no source, licence or confirmation")


def _reference_stats():
    from .input_quality import REFERENCE
    return (OK, "training-image ranges measured") if REFERENCE.exists() else (FAIL, "reference ranges not measured (app/scripts/reference_image_stats.py)")


def _retention_set():
    days = uploads.policy().get("upload_retention_days")
    return (OK, f"uploads are deleted after {days} days") if days else (FAIL, "no retention period set: uploads are kept until deleted")


def _thresholds_versioned():
    with tx() as c:
        have = {r["key"] for r in rows(c, "SELECT DISTINCT key FROM sem.thresholds")}
    missing = sorted(set(semantic.LIMITS) - have)
    return (OK, f"{len(have)} thresholds, each change a new row") if not missing else (FAIL, "no stored value for: " + ", ".join(missing))


def _live_precision_ok():
    lp = monitoring.live_precision()
    if not lp["enough_data"]:
        return UNKNOWN, f"{lp['overall']['decided']} of {lp['window']} decided alerts needed"
    p = lp["overall"]["precision"]
    return (OK, f"{p:.0%} confirmed (floor {lp['floor']:.0%})") if not lp["below_floor"] else (FAIL, f"{p:.0%} confirmed, below the floor of {lp['floor']:.0%}")


def _drift_ok():
    d = monitoring.drift()
    if d["last_30_days"]["n"] < 5:
        return UNKNOWN, f"{d['last_30_days']['n']} uploads in the last 30 days (5 needed)"
    return (FAIL, "the share of unusual uploads is rising") if d["rising"] else (OK, "no rise in unusual uploads")


def _incidents_handled():
    with tx() as c:
        r = one(c, "SELECT count(*) AS n FROM gov.incidents WHERE state <> 'closed' AND severity IN ('high', 'serious') AND opened_at < now() - interval '7 days'")
    return (OK, "no urgent incident open longer than 7 days") if not r["n"] else (FAIL, f"{r['n']} urgent incident(s) open longer than 7 days")


def _risks_reviewed():
    rs = risks.list_risks()
    late = [r["id"] for r in rs if r["overdue"]]
    return (OK, f"{len(rs)} risks, none overdue") if not late else (FAIL, "overdue: " + ", ".join(late))


def _access_review_current():
    with tx() as c:
        late = [r["username"] for r in rows(c, "SELECT u.username FROM iam.users u WHERE u.active AND NOT EXISTS (SELECT 1 FROM gov.access_reviews a "
                                               "WHERE a.username = u.username AND a.reviewed_at > now() - interval '92 days') ORDER BY 1")]
    return (OK, "every active account reviewed in the last 3 months") if not late else (FAIL, f"{len(late)} account(s) not reviewed in 3 months")


def _two_step_coverage():
    from . import auth
    need = [n for n, u in auth.users().items() if u["active"] and auth.perms_of(u["role"]) & auth.TWO_STEP_FOR]
    without = [n for n in need if not auth.users()[n].get("two_step")]
    if not need:
        return UNKNOWN, "no administrators or officers"
    return (OK, f"all {len(need)} administrators and officers") if not without else (FAIL, f"{len(without)} of {len(need)} administrators and officers without it")


def _demo_accounts_off():
    return (FAIL, "demo accounts with the published password are on") if seed.enabled() else (OK, "demo accounts are off")


LIVE = {"audit_chain": _audit_chain, "approved_model_hash": _approved_model_hash, "approved_model_gate": _approved_model_gate,
        "approved_run_record": _approved_run_record, "approved_model_card": _approved_model_card, "seeds_measured": _seeds_measured,
        "unseen_measured": _unseen_measured, "robustness_measured": _robustness_measured, "previous_model_available": _previous_model_available,
        "licence_recorded": _licence_recorded, "leakage_free": _leakage_free, "uploads_have_rights": _uploads_have_rights, "reference_stats": _reference_stats,
        "retention_set": _retention_set, "thresholds_versioned": _thresholds_versioned, "live_precision_ok": _live_precision_ok, "drift_ok": _drift_ok,
        "incidents_handled": _incidents_handled, "risks_reviewed": _risks_reviewed, "access_review_current": _access_review_current,
        "two_step_coverage": _two_step_coverage, "demo_accounts_off": _demo_accounts_off}


# ---- evidence --------------------------------------------------------------------------------------------------------

def _resolve(ref: str) -> Path:
    return (APP / ref).resolve()


def _test_results() -> dict:
    try:
        return json.loads(TEST_RESULTS.read_text())
    except (OSError, ValueError):
        return {}


def _check(ev: dict, results: dict) -> dict:
    kind = ev["type"]
    try:
        if kind == "test":
            path, _, name = ev["ref"].partition("::")
            f = _resolve(path)
            if not f.exists() or f"def {name}(" not in f.read_text():
                return {**ev, "status": FAIL, "detail": "the test does not exist"}
            r = (results.get("tests") or {}).get(name)
            if r is None:
                return {**ev, "status": UNKNOWN, "detail": "exists; no recorded run"}
            return {**ev, "status": OK if r == "passed" else FAIL, "detail": f"{r} on {results.get('finished_utc', '?')} UTC"}
        if kind == "live":
            st, detail = LIVE[ev["check"]]()
            return {**ev, "status": st, "detail": detail}
        if kind == "file":
            f = _resolve(ev["ref"])
            return {**ev, "status": OK if f.exists() else FAIL, "detail": "present" if f.exists() else "missing"}
        if kind == "file_contains":
            f = _resolve(ev["ref"])
            ok = f.exists() and ev["text"] in f.read_text()
            return {**ev, "status": OK if ok else FAIL, "detail": "present" if ok else "not found"}
        if kind == "record":
            folder, pattern = _resolve(ev["ref"]).parent, Path(ev["ref"]).name
            dates = sorted(d for p in folder.glob(pattern) for d in re.findall(r"(\d{4}-\d{2}-\d{2})", p.name))
            if not dates:
                return {**ev, "status": FAIL, "detail": "never done"}
            age = (date.today() - date.fromisoformat(dates[-1])).days
            return {**ev, "status": OK if age <= ev["max_age_days"] else FAIL, "detail": f"last on {dates[-1]} ({age} days ago)"}
    except Exception as e:  # noqa: BLE001  a check that cannot run is reported, not hidden
        return {**ev, "status": UNKNOWN, "detail": f"could not be checked: {type(e).__name__}: {e}"}
    return {**ev, "status": UNKNOWN, "detail": f"unknown evidence type {kind}"}


def _status(states: list) -> str:
    if states and all(s == OK for s in states):
        return "met"
    if any(s == OK for s in states):
        return "partly met"
    if states and all(s == UNKNOWN for s in states):
        return "not measured"
    return "not met"


def register() -> dict:
    """Every control with its evidence checked now, and each framework requirement scored."""
    results = _test_results()
    cs = []
    for c in controls()["controls"]:
        ev = [_check(e, results) for e in c["evidence"]]
        cs.append({**c, "evidence": ev, "status": _status([e["status"] for e in ev])})
    by_id = {c["id"]: c for c in cs}
    fws = []
    for f in frameworks()["frameworks"]:
        reqs = []
        for r in f["requirements"]:
            mapped = [c["id"] for c in cs if r["id"] in c["frameworks"].get(f["key"], [])]
            st = [by_id[i]["status"] for i in mapped]
            status = "met" if st and all(s == "met" for s in st) else "partly met" if any(s in ("met", "partly met") for s in st) else "not met"
            reqs.append({**r, "controls": mapped, "status": status})
        met = sum(r["status"] == "met" for r in reqs)
        part = sum(r["status"] == "partly met" for r in reqs)
        fws.append({**{k: f[k] for k in ("key", "name", "role", "how")}, "requirements": reqs, "met": met, "partly": part, "total": len(reqs),
                    "score": round((met + 0.5 * part) / len(reqs), 3) if reqs else None})
    counts = {s: sum(c["status"] == s for c in cs) for s in ("met", "partly met", "not met", "not measured")}
    return {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "tests_run_utc": results.get("finished_utc"),
            "stages": controls()["stages"], "controls": cs, "counts": counts, "frameworks": fws}


# ---- data register and access reviews -------------------------------------------------------------------------------

def data_register() -> dict:
    with tx() as c:
        ups = rows(c, "SELECT u.id, u.name, u.unit_id, u.created_by, u.disaster_type, u.source, u.licence, u.rights_confirmed_by, "
                      "to_char(u.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS created, (u.input_quality->>'unusual')::boolean AS unusual, "
                      "(u.input_quality->>'empty_share')::float AS empty_share, (u.meta->'privacy'->'removed') AS metadata_removed, "
                      "(SELECT count(*) FROM core.assessments a WHERE a.upload_id = u.id) AS assessments, "
                      "(SELECT bool_or(a.abstained) FROM core.assessments a WHERE a.upload_id = u.id) AS abstained "
                      "FROM ingest.uploads u ORDER BY u.created_at DESC LIMIT 500")
    pol = uploads.policy()
    days = pol.get("upload_retention_days")
    for u in ups:
        u["delete_after"] = (date.fromisoformat(u["created"]).toordinal() + days) if days else None
        if u["delete_after"]:
            u["delete_after"] = date.fromordinal(u["delete_after"]).isoformat()
    sheet = (GOV / "datasheet_xbd.md").read_text() if (GOV / "datasheet_xbd.md").exists() else ""
    datasets = [{"name": "xBD (train, tier3, test, hold)", "use": "training and evaluation", "pairs": 22068, "source": "xview2.org",
                 "licence": "to confirm (datasheet section 6)" if "[to confirm]" in sheet else "recorded in the datasheet",
                 "verified": _leakage_free()[1], "hashes": "configs/xbd_sha1.txt", "datasheet": "governance/datasheet_xbd.md"}]
    return {"datasets": datasets, "uploads": ups, "retention_days": days, "notice": pol.get("notice")}


def access_reviews(user: dict) -> list:
    from . import auth
    vis = auth.visible_units(user)
    with tx() as c:
        last = {r["username"]: r for r in rows(c, "SELECT DISTINCT ON (username) username, decision, note, reviewed_by, "
                                                  "to_char(reviewed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS reviewed, reviewed_at > now() - interval '92 days' AS current "
                                                  "FROM gov.access_reviews ORDER BY username, reviewed_at DESC")}
    out = []
    for name, rec in auth.users().items():
        if rec["unit"] not in vis:
            continue
        l = last.get(name)
        out.append({"username": name, "name": rec["name"], "role": rec["role"], "unit": rec["unit"], "active": rec["active"],
                    "last_login_utc": rec.get("last_login_utc"), "two_step": bool(rec.get("two_step")),
                    "last_review": l, "due": rec["active"] and not (l and l["current"])})
    return sorted(out, key=lambda r: (not r["due"], r["username"]))


def review_access(username: str, decision: str, note: str, user: dict) -> dict:
    from . import auth
    if decision not in ("keep", "disable"):
        raise ValueError("decision is keep or disable")
    if username == user["username"]:
        raise ValueError("someone else must review your own account")
    rec = auth.get_user(username)
    if not rec or rec["unit"] not in auth.visible_units(user):
        raise KeyError(username)
    if decision == "disable" and len((note or "").strip()) < 5:
        raise ValueError("say why the account is no longer needed")
    with tx() as c:
        run(c, "INSERT INTO gov.access_reviews (username, decision, note, reviewed_by) VALUES (:u, :d, :n, :b)", u=username, d=decision, n=(note or "").strip(), b=user["username"])
    if decision == "disable" and rec["active"]:
        auth.update_user(username, active=False)
    audit.log("access_review", user["username"], None, username=username, decision=decision, note=note)
    return {"username": username, "decision": decision}


# ---- technical file -------------------------------------------------------------------------------------------------

def technical_file() -> str:
    reg = register()
    approved = semantic.approved_model()
    mid = approved.get("default_model")
    out = ["# EnviroSense technical file", "",
           f"Produced {reg['checked_utc']} UTC from the live records (api/compliance.py). Structure after EU AI Act Annex IV; the Act is used as a benchmark, "
           "not a legal requirement in Pakistan. Nothing here is typed by hand.", "",
           "## 1. General description and intended use", "", (GOV / "intended_use.md").read_text() if (GOV / "intended_use.md").exists() else "(missing)", "",
           "## 2. The approved model", "",
           f"- Model: `{mid}`, approved {approved.get('approved_utc')} by {approved.get('approved_by')}; checkpoint `{approved.get('checkpoint_sha256')}`.",
           f"- Reason: {approved.get('reason')}", ""]
    if mid and mid in service.models():
        sc = model_registry.scorecard(mid)
        out += ["| Criterion | Pass mark | Measured | Result |", "| --- | --- | --- | --- |"]
        out += [f"| {r['id']} {r['text']} | {r['op']} {r['value']} | {r['measured'] if r['measured'] is not None else '–'} | {r['status']} |" for r in sc["criteria"]]
        out += ["", model_registry.card(mid)["markdown"], ""]
    out += ["## 3. Controls", "", f"{reg['counts']['met']} met, {reg['counts']['partly met']} partly met, {reg['counts']['not met']} not met, "
            f"{reg['counts']['not measured']} not measured, of {len(reg['controls'])}. Tests last run {reg['tests_run_utc'] or 'never recorded'} UTC.", "",
            "| Control | Stage | Rule | Owner | Status | Evidence |", "| --- | --- | --- | --- | --- | --- |"]
    for c in reg["controls"]:
        ev = "; ".join(f"{e.get('ref') or e.get('check')}: {e['detail']}" for e in c["evidence"])
        out.append(f"| {c['id']} {c['name']} | {c['stage']} | {c['rule']} | {c['owner']} | {c['status']} | {ev.replace('|', '/')} |")
    out += ["", "## 4. Frameworks", ""]
    for f in reg["frameworks"]:
        out += [f"### {f['name']}: {f['met']} met, {f['partly']} partly, of {f['total']}", "", f["how"], "",
                "| Requirement | Controls | Status |", "| --- | --- | --- |"]
        out += [f"| {r['id']} {r['title']} | {', '.join(r['controls'])} | {r['status']} |" for r in f["requirements"]]
        out.append("")
    m = monitoring.summary()
    lp = m["live_precision"]["overall"]
    out += ["## 5. Post-release monitoring", "",
            f"- Live precision: {lp['precision'] if lp['precision'] is not None else 'no decided alerts yet'} over {lp['decided']} decided alerts "
            f"(floor {m['live_precision']['floor']}, window {m['live_precision']['window']}).",
            f"- Abstention, last 30 days: {m['abstention']['abstained']} of {m['abstention']['total']} assessments.",
            f"- Unusual uploads, last 30 days: {m['drift']['last_30_days']['unusual']} of {m['drift']['last_30_days']['n']}.",
            f"- Open incidents: {m['incidents']['open']} ({m['incidents']['urgent']} high or serious).", "",
            "## 6. Risk register", "", "| Risk | Stage | Score | Controls | Status | Next review |", "| --- | --- | --- | --- | --- | --- |"]
    out += [f"| {r['id']} {r['risk']} | {r['stage']} | {r['score']} | {', '.join(r['controls'])} | {r['status']} | {r['next_review']} |" for r in risks.list_risks()]
    out += ["", "## 7. Decision log", "", decisions.markdown(), ""]
    return "\n".join(out)
