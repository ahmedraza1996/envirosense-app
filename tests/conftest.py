import pytest

from app.api import audit


@pytest.fixture(autouse=True)
def _isolated_audit_log(tmp_path, monkeypatch):
    """Tests must never write to the real audit log."""
    monkeypatch.setattr(audit, "PATH", tmp_path / "audit" / "audit.jsonl")
