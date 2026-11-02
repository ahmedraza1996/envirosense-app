import pytest
from starlette.testclient import TestClient

from app.api import accounts, audit, auth, engines


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Tests must never write to the real audit log, user store or approved-model file; and they sign in as a test officer
    (a request that carries its own Authorization header is left alone)."""
    monkeypatch.setattr(audit, "PATH", tmp_path / "audit" / "audit.jsonl")
    monkeypatch.setattr(auth, "DIR", tmp_path / "auth")
    approved = tmp_path / "approved_model.json"
    approved.write_text('{"default_model": "unet_paired_mis"}')
    monkeypatch.setattr(engines, "APPROVED", approved)
    monkeypatch.setattr(accounts, "DECISION_LOG", tmp_path / "decision_log.md")
    auth._fails.clear()
    auth.bootstrap()
    top = next(iter(auth.units()))
    auth.create_user("test_officer", "Test Officer", "officer", top, "Officer-pass-1", "test", must_change=False)
    token = auth.make_token("test_officer")
    real = TestClient.request

    def request(self, method, url, **kw):
        if "Authorization" not in (kw.get("headers") or {}) and "authorization" not in (kw.get("headers") or {}):
            kw["headers"] = {**(kw.get("headers") or {}), "Authorization": f"Bearer {token}"}
        return real(self, method, url, **kw)
    monkeypatch.setattr(TestClient, "request", request)


@pytest.fixture()
def login_as():
    """login_as(username, role, unit=None) -> Authorization headers for a (new) user; unit defaults to the top unit."""
    def make(username, role="analyst", unit=None):
        if username not in auth.users():
            auth.create_user(username, username.replace("_", " ").title(), role, unit or next(iter(auth.units())), "Passw0rd-long-1", "test", must_change=False)
        return {"Authorization": f"Bearer {auth.make_token(username)}"}
    return make
