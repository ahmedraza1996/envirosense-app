"""Model registry and release gate.

Every model the server can load is a model version (sem.model_versions) with a scorecard: its own run records checked against the acceptance criteria
(governance/acceptance_criteria.json, written before the final runs). Each criterion passes, fails, or is not measured. The release gate is open only
when every criterion passes; otherwise a change of the approved model must carry a written exception (what is missing and why release anyway), which
the second administrator sees before approving and which is kept in the decision log. Rolling back is asking for the previous model the same way.

The model card is the one the training run wrote (runs/<run>/model_card.md, src/model_card.py); when a run has none, a draft is generated from the same
records and shown as a draft (criterion AC-7b stays unmet until the run writes its own).
"""
import json
from pathlib import Path

from ..db import semantic
from . import service

CRITERIA = Path(__file__).resolve().parents[1] / "governance" / "acceptance_criteria.json"
EXCEPTION_MIN = 20


def criteria() -> dict:
    return json.loads(CRITERIA.read_text())


def _card_module():
    import model_card                       # src/ is on sys.path (api/engines.py)
    return model_card


def _judge(value, op, target):
    if value is None:
        return "not measured"
    ok = value >= target if op == ">=" else value <= target if op == "<=" else value == target
    return "pass" if ok else "fail"


def scorecard(model_id: str) -> dict:
    m = service.models().get(model_id)
    if m is None or not m.get("run_dir"):
        derived = {}
    else:
        derived = _card_module().evidence(Path(m["run_dir"]))["derived"]
    rows = []
    for c in criteria()["criteria"]:
        v = derived.get(c["metric"])
        rows.append({**c, "measured": v, "status": _judge(v, c["op"], c["value"])})
    failed = [r["id"] for r in rows if r["status"] == "fail"]
    missing = [r["id"] for r in rows if r["status"] == "not measured"]
    return {"model": model_id, "criteria": rows, "passed": sum(r["status"] == "pass" for r in rows), "failed": failed, "missing": missing,
            "gate_open": not failed and not missing}


def gate_problems(sc: dict) -> str:
    by = {r["id"]: r for r in sc["criteria"]}
    parts = [f"{i} {by[i]['text'].lower()} ({'not measured' if by[i]['status'] == 'not measured' else 'missed: ' + str(by[i]['measured'])})"
             for i in sc["failed"] + sc["missing"]]
    return "; ".join(parts)


def check_release(model_id: str, exception: str | None) -> dict:
    """Raises ValueError when the gate is closed and no adequate written exception is given. Returns what goes into the approval request."""
    sc = scorecard(model_id)
    exception = (exception or "").strip()
    if not sc["gate_open"] and len(exception) < EXCEPTION_MIN:
        raise ValueError(f"the release gate is closed for {model_id}: {gate_problems(sc)}. To release it anyway, give a written exception "
                         f"(at least {EXCEPTION_MIN} characters) saying why; the approver sees it and it goes to the decision log")
    return {"gate_open": sc["gate_open"], "failed": sc["failed"], "missing": sc["missing"], "exception": exception or None}


def registry() -> list:
    versions = {v["id"]: v for v in semantic.model_versions()}
    out = []
    for mid, m in service.models().items():
        if m["kind"] != "unet":
            continue
        sc = scorecard(mid)
        v = versions.get(mid, {})
        run_dir = Path(m["run_dir"])
        out.append({"id": mid, "label": m.get("label", mid), "run": run_dir.name, "status": v.get("status", "candidate"),
                    "approved_by": v.get("approved_by"), "approved_utc": v.get("approved_utc"), "checkpoint_sha256": v.get("checkpoint_sha256"),
                    "test_score": m.get("test_score"), "hold_score": sc_value(sc, "hold.score", run_dir),
                    "passed": sc["passed"], "failed": sc["failed"], "missing": sc["missing"], "gate_open": sc["gate_open"],
                    "card_saved": (run_dir / "model_card.md").exists()})
    out.sort(key=lambda r: (r["status"] != "approved", -(r["test_score"] or 0)))
    return out


def sc_value(sc: dict, metric: str, run_dir: Path):
    return _card_module().evidence(run_dir)["derived"].get(metric)


def card(model_id: str) -> dict:
    m = service.models().get(model_id)
    if m is None or not m.get("run_dir"):
        raise KeyError(model_id)
    run_dir = Path(m["run_dir"])
    saved = run_dir / "model_card.md"
    if saved.exists():
        return {"model": model_id, "draft": False, "markdown": saved.read_text()}
    return {"model": model_id, "draft": True, "markdown": _card_module().card(run_dir)}


def detail(model_id: str) -> dict:
    if model_id not in service.models():
        raise KeyError(model_id)
    m = service.models()[model_id]
    ev = _card_module().evidence(Path(m["run_dir"]))
    return {"id": model_id, "label": m.get("label", model_id), "scorecard": scorecard(model_id), "config": ev["config"], "metrics": ev["metrics"],
            "robustness": ev["robustness"], "calibration": {k: ev["calibration"].get(k) for k in ("ece_before", "accuracy_pixels", "coverage_risk_after")},
            "version": next((v for v in semantic.model_versions() if v["id"] == model_id), None)}
