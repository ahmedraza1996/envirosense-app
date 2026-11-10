"""Demo accounts: written at start with the shared password, idempotent, listed for the sign-in page, and left alone when switched off."""
from fastapi.testclient import TestClient

from app.api import auth, seed
from app.api.main import app


def test_demo_accounts_are_seeded_with_the_shared_password_and_listed(monkeypatch):
    monkeypatch.setenv("ENVIROSENSE_DEMO_ACCOUNTS", "1")
    assert set(seed.ensure()) == {u for u, *_ in seed.USERS}
    assert seed.ensure() == []                                     # the next start has nothing to change
    for username, _, role, _ in seed.USERS:
        u = auth.get_user(username)
        assert u["role"] == role and u["active"] and not u["must_change"] and auth.check_password(seed.PASSWORD, u["pw"])
    units = auth.units()
    assert {n for _, _, n, _ in seed.UNITS} <= {u["name"] for u in units.values()}
    auth.update_user("karachi.analyst1", role="officer", active=False)  # someone changed a demo account during a demonstration
    assert seed.ensure() == ["karachi.analyst1"]
    assert auth.get_user("karachi.analyst1")["role"] == "analyst" and auth.get_user("karachi.analyst1")["active"]
    r = TestClient(app).get("/api/auth/demo-accounts")
    assert r.status_code == 200 and r.json()["password"] == seed.PASSWORD
    assert {a["role"] for a in r.json()["accounts"]} == {"admin", "officer", "analyst", "auditor"}


def test_switched_off_the_accounts_are_left_alone_and_not_listed(monkeypatch):
    monkeypatch.setenv("ENVIROSENSE_DEMO_ACCOUNTS", "0")
    assert seed.ensure() == []
    assert auth.get_user("karachi.analyst1") is None
    assert TestClient(app).get("/api/auth/demo-accounts").status_code == 404
