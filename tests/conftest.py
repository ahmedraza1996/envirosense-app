import os

os.environ["ENVIROSENSE_TEST_DB"] = "1"          # before anything opens a connection: the suite runs on envirosense_test, never on the real database

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from starlette.testclient import TestClient

from app.api import approvals, auth, engines, uploads
from app.db import engine as dbe
from app.db import semantic

APP = Path(__file__).resolve().parents[1]
RESET = ("audit.log, iam.sessions, iam.login_throttle, iam.users, iam.units, ingest.job_steps, ingest.jobs, ingest.uploads, "
         "core.alerts, core.assessments, wf.alert_review_events, wf.alert_reviews, wf.approval_requests, sem.model_versions")


def migrate(target="head"):
    cfg = Config(str(APP / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP / "db" / "migrations"))
    return command.upgrade(cfg, target) if target == "head" else command.downgrade(cfg, target)


@pytest.fixture(scope="session", autouse=True)
def _database():
    """The real schema from the migrations, built from scratch once per run (this also proves they go down and up again)."""
    migrate("base")
    migrate("head")
    yield
    dbe.dispose()


def reset_database():
    with dbe.engine("owner").begin() as c:
        c.exec_driver_sql("ALTER TABLE audit.log DISABLE TRIGGER USER")        # the audit log refuses truncation; only the owner clears it, between tests
        c.exec_driver_sql(f"TRUNCATE {RESET} RESTART IDENTITY CASCADE")
        c.exec_driver_sql("ALTER TABLE audit.log ENABLE TRIGGER USER")
        c.exec_driver_sql("DELETE FROM sem.thresholds WHERE set_by <> 'migration'")
        c.exec_driver_sql("DELETE FROM iam.roles WHERE NOT builtin")
    semantic._threshold_cache.clear()
    auth.invalidate_roles()


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Every test starts from an empty database (reference data kept), never touches the real approved-model seed or decision log,
    and signs in as a test officer (a request that carries its own Authorization header is left alone)."""
    reset_database()
    monkeypatch.setattr(auth, "DIR", tmp_path / "auth")
    approved = tmp_path / "approved_model.json"
    approved.write_text('{"default_model": "unet_paired_mis", "approved_by": "seed (test)", "reason": "test seed"}')
    monkeypatch.setattr(engines, "APPROVED", approved)
    monkeypatch.setattr(approvals, "DECISION_LOG", tmp_path / "decision_log.md")
    models = engines.discover_models()
    models.setdefault("unet_paired_mis", {"label": "Paired U-Net (misalignment)", "kind": "unet"})
    semantic.sync_models(models, approved)
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


def only_admin(username):
    """Make `username` the one active administrator, so a sensitive change is made at once (nobody else could approve it)."""
    for name, rec in auth.users().items():
        if rec["role"] == "admin" and name != username and rec["active"]:
            auth.update_user(name, active=False)


@pytest.fixture()
def login_as():
    """login_as(username, role, unit=None) -> Authorization headers for a (new) user; unit defaults to the top unit."""
    def make(username, role="analyst", unit=None):
        if auth.get_user(username) is None:
            auth.create_user(username, username.replace("_", " ").title(), role, unit or next(iter(auth.units())), "Passw0rd-long-1", "test", must_change=False)
        return {"Authorization": f"Bearer {auth.make_token(username)}"}
    return make


@pytest.fixture()
def make_upload(tmp_path, monkeypatch):
    """make_upload(unit, by, name, age_days=0, job=None, **meta) -> upload id: the folder on disk and the rows in the database.
    job is None (no job), or the state of the job: queued, running, succeeded, failed."""
    monkeypatch.setattr(uploads, "UPLOADS", tmp_path / "uploads")

    def make(unit, by="test", name="upload", age_days=0, job="succeeded", **meta):
        uid, d = uploads.new_folder()
        created = (datetime.now(timezone.utc) - timedelta(days=age_days)).strftime("%Y-%m-%d %H:%M:%S+00")
        uploads.register(uid, {"name": name, "disaster_type": "fire", "event_date": None, "model_id": "m", "after_file": "after_input.jpg",
                               "created_utc": created, **meta}, unit, by, queue=False)
        if job:
            with dbe.tx() as c:
                dbe.run(c, "INSERT INTO ingest.jobs (upload_id, state, step, heartbeat_at, finished_at) VALUES (:u, :s, 'x', now(), CASE WHEN :s IN ('succeeded','failed') THEN now() END)", u=uid, s=job)
        return uid
    make.folder = lambda uid: uploads.UPLOADS / uid
    return make
