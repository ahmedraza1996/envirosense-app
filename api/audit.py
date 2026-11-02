"""Append-only audit log with a hash chain (control X1 of governance/control_matrix.md).

One JSON line per action that changes something or releases something: assessment, review, retraction, export, map offset,
upload, delete, model approval. Each line carries the hash of the previous line, so a removed or edited line breaks the chain and
`verify` says where. It records who did it (the signed-in account, with its unit and role), when, to which assessment, and the
versions involved. It is a record for accountability on a research prototype, not a security product: anyone with access to
the server's files can rewrite the whole chain.
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

from . import auth
from .engines import ROOT

PATH = ROOT / "runs" / "app" / "audit" / "audit.jsonl"
GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _last() -> tuple[int, str]:
    if not PATH.exists() or PATH.stat().st_size == 0:
        return 0, GENESIS
    with PATH.open("rb") as f:
        f.seek(max(0, PATH.stat().st_size - 8192))
        tail = f.read().decode(errors="ignore").strip().splitlines()
    last = json.loads(tail[-1])
    return last["seq"], last["hash"]


def log(action: str, actor: str | None, assessment: str | None = None, **detail) -> dict:
    u = auth.current()
    if u:                                   # who, from which unit and in which role: for scoping what an administrator or auditor sees
        detail.setdefault("actor_unit", u["unit"])
        detail.setdefault("actor_role", u["role"])
    with _lock:
        seq, prev = _last()
        entry = {"seq": seq + 1, "utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "action": action,
                 "actor": (actor or "").strip() or "unknown", "assessment": assessment, "detail": detail, "prev": prev}
        entry["hash"] = _digest(entry)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


def read(assessment: str | None = None, limit: int = 200) -> list:
    if not PATH.exists():
        return []
    rows = [json.loads(line) for line in PATH.read_text().splitlines() if line.strip()]
    if assessment:
        rows = [r for r in rows if r.get("assessment") == assessment]
    return rows[-limit:]


def verify() -> dict:
    """Walk the chain. ok is False at the first line whose hash or link does not match."""
    prev, n = GENESIS, 0
    if PATH.exists():
        for i, line in enumerate(PATH.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                return {"ok": False, "entries": n, "first_bad_line": i, "reason": "unreadable line"}
            if e.get("prev") != prev or e.get("hash") != _digest(e) or e.get("seq") != n + 1:
                return {"ok": False, "entries": n, "first_bad_line": i, "reason": "hash chain broken"}
            prev, n = e["hash"], n + 1
    return {"ok": True, "entries": n, "first_bad_line": None, "reason": ""}
