"""Governance modules: incidents, risk register, decision log and access reviews as rows (schema gov); rights and licence of uploaded imagery; abstention and
input quality on assessments; how a review was made; the alert rule and the monitoring floors as versioned thresholds; route rules for the new screens

Revision ID: 0007
Revises: 0006
"""
import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

GOVERNANCE = Path(__file__).resolve().parents[3] / "governance"

PERMISSIONS = [
    ("incident_manage", "Assess, close and reopen incidents", True),
    ("risk_manage", "Edit the risk register", True),
]
GRANTS = [("admin", "incident_manage"), ("officer", "incident_manage"), ("admin", "risk_manage")]

# (key, value, note): the alert rule (was a constant in api/alerts.py) and the floors the monitoring and the abstention use
THRESHOLDS = [
    ("alert_min_severe_m2", 250, "Severely damaged roof area that raises an area alert (about three houses)"),
    ("alert_eps_m", 30, "Damage within this distance belongs to one area"),
    ("alert_majority", 0.5, "An alert is high severity when at least this share of the building area is severely damaged"),
    ("abstain_low_conf_share", 0.6, "The whole image is not assessed when more than this share of the structures is below the review confidence"),
    ("unusual_max_outside", 2, "An image is unusual when more than this many of its statistics fall outside the range of the training images"),
    ("blank_max_share", 0.4, "An image is not assessed when more than this share of it is blank or cloud"),
    ("live_precision_floor", 0.6, "An incident is raised when fewer than this share of the last reviewed alerts were confirmed"),
    ("live_precision_window", 30, "Number of most recent decided alerts the live precision is measured on"),
    ("drift_ratio", 2.0, "An incident is raised when the share of unusual uploads in the last 30 days is this many times the 30 days before"),
    ("rubber_stamp_seconds", 5, "A confirmation decided faster than this, or without opening the evidence, counts as a possible rubber stamp"),
]

# first matching rule wins: the report rule goes before the general 'view' rule for assessments (position 0 sorts first)
REPORT_RULE = (0, "GET", "/api/assessments/[^/]+/(report\\.(md|html)|report-map\\.png)", "export")
RULES = [
    ("GET", "/api/gov/(controls|frameworks|technical-file\\.md|models(/[^/]+(/card)?)?|data|decisions|risks)", "audit"),
    ("POST", "/api/gov/checks", "audit"),
    ("(POST|PUT)", "/api/gov/risks(/[^/]+)?", "risk_manage"),
    ("GET", "/api/gov/(monitoring|incidents(/[^/]+)?)", "any"),
    ("POST", "/api/gov/incidents", "any"),
    ("POST", "/api/gov/incidents/[^/]+/(assess|close|reopen|note)", "incident_manage"),
    ("(GET|POST)", "/api/gov/access-reviews", "users"),
    ("POST", "/api/auth/two-step/(setup|enable|disable)", "any"),
]

DDL = """
CREATE SCHEMA gov;

-- an incident: something went wrong or may have (a wrong alert, a quality floor crossed, a broken audit chain); raised by a person or by a check
CREATE TABLE gov.incidents (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('wrong_alert', 'model_quality', 'data_drift', 'security', 'audit_chain', 'access', 'other')),
  severity     text NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'serious')),
  title        text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 5 AND 160),
  description  text NOT NULL DEFAULT '',
  source       text NOT NULL CHECK (source IN ('person', 'check')),
  dedup_key    text,
  state        text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'investigating', 'closed')),
  opened_by    text NOT NULL,
  opened_at    timestamptz NOT NULL DEFAULT now(),
  unit_id      text,
  links        jsonb NOT NULL DEFAULT '{}',
  closed_by    text,
  closed_at    timestamptz,
  cause        text,
  resolution   text,
  CONSTRAINT closed_has_resolution CHECK (state <> 'closed' OR (closed_by IS NOT NULL AND char_length(btrim(coalesce(resolution, ''))) >= 10
                                                                AND char_length(btrim(coalesce(cause, ''))) >= 5))
);
CREATE UNIQUE INDEX incident_one_open_per_key ON gov.incidents (dedup_key) WHERE state <> 'closed' AND dedup_key IS NOT NULL;
CREATE INDEX incidents_state ON gov.incidents (state, opened_at DESC);

CREATE TABLE gov.incident_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  incident_id  bigint NOT NULL REFERENCES gov.incidents (id),
  at           timestamptz NOT NULL DEFAULT now(),
  actor        text NOT NULL,
  action       text NOT NULL CHECK (action IN ('opened', 'assessed', 'note', 'closed', 'reopened')),
  note         text NOT NULL DEFAULT '',
  detail       jsonb NOT NULL DEFAULT '{}'
);

-- the decision log: every default, threshold, release and scope decision with its reason and who took it
CREATE TABLE gov.decisions (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at           timestamptz NOT NULL DEFAULT now(),
  kind         text NOT NULL,
  decision     text NOT NULL CHECK (char_length(btrim(decision)) >= 5),
  reason       text NOT NULL CHECK (char_length(btrim(reason)) >= 5),
  decided_by   text NOT NULL,
  approved_by  text,
  ref          text,
  detail       jsonb NOT NULL DEFAULT '{}'
);

-- the risk register (was governance/risk_register.csv): edited only through the application, every edit is an audit row
CREATE TABLE gov.risks (
  id           text PRIMARY KEY CHECK (id ~ '^R[0-9]{2,3}$'),
  stage        text NOT NULL,
  risk         text NOT NULL,
  cause        text NOT NULL DEFAULT '',
  likelihood   smallint NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
  severity     smallint NOT NULL CHECK (severity BETWEEN 1 AND 5),
  score        smallint GENERATED ALWAYS AS (likelihood * severity) STORED,
  controls     text[] NOT NULL DEFAULT '{}',
  planned      text NOT NULL DEFAULT '',
  owner        text NOT NULL,
  residual     text NOT NULL DEFAULT '',
  status       text NOT NULL CHECK (status IN ('open', 'reduced', 'accepted', 'closed')),
  next_review  date NOT NULL,
  updated_by   text NOT NULL DEFAULT 'migration',
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- access reviews: an administrator confirms every so often that each account is still needed
CREATE TABLE gov.access_reviews (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username     text NOT NULL REFERENCES iam.users (username) ON UPDATE CASCADE,
  decision     text NOT NULL CHECK (decision IN ('keep', 'disable')),
  note         text NOT NULL DEFAULT '',
  reviewed_by  text NOT NULL,
  reviewed_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT not_self CHECK (reviewed_by <> username)
);
CREATE INDEX access_reviews_user ON gov.access_reviews (username, reviewed_at DESC);

-- records: history and the decision log are never edited
CREATE FUNCTION gov.no_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%% is a record and cannot be changed', TG_TABLE_NAME USING ERRCODE = '42501';
END $$;
CREATE TRIGGER decisions_fixed BEFORE UPDATE OR DELETE ON gov.decisions FOR EACH ROW EXECUTE FUNCTION gov.no_change();
CREATE TRIGGER incident_events_fixed BEFORE UPDATE OR DELETE ON gov.incident_events FOR EACH ROW EXECUTE FUNCTION gov.no_change();
CREATE TRIGGER access_reviews_fixed BEFORE UPDATE OR DELETE ON gov.access_reviews FOR EACH ROW EXECUTE FUNCTION gov.no_change();
CREATE TRIGGER thresholds_fixed BEFORE UPDATE OR DELETE ON sem.thresholds FOR EACH ROW EXECUTE FUNCTION gov.no_change();

-- an incident is not deleted; once closed it changes only by being reopened
CREATE FUNCTION gov.incident_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'an incident cannot be deleted' USING ERRCODE = '42501';
  END IF;
  IF OLD.state = 'closed' AND NEW.state = 'closed' THEN
    RAISE EXCEPTION 'a closed incident is a record; reopen it to change it' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER incident_guard BEFORE UPDATE OR DELETE ON gov.incidents FOR EACH ROW EXECUTE FUNCTION gov.incident_guard();

-- imagery: where it came from, under which licence, who confirmed the right to process it
ALTER TABLE ingest.uploads ADD COLUMN source text, ADD COLUMN licence text, ADD COLUMN rights_confirmed_by text,
  ADD COLUMN input_quality jsonb NOT NULL DEFAULT '{}';
-- assessments: whether the system declined to assess, and why
ALTER TABLE core.assessments ADD COLUMN abstained boolean NOT NULL DEFAULT false, ADD COLUMN abstain_reasons text[] NOT NULL DEFAULT '{}',
  ADD COLUMN rule_version bigint;
-- two-step sign-in (TOTP, RFC 6238): the shared secret, and when the user proved they hold it (until then it is not required)
ALTER TABLE iam.users ADD COLUMN totp_secret text, ADD COLUMN totp_enabled_at timestamptz;
-- how a decision was made: seconds from opening the alert to the decision, and whether the evidence was opened
ALTER TABLE wf.alert_review_events ADD COLUMN seconds_to_decide numeric, ADD COLUMN evidence_viewed boolean;

GRANT USAGE ON SCHEMA gov TO envirosense_app;
GRANT SELECT, INSERT, UPDATE ON gov.incidents, gov.risks TO envirosense_app;
GRANT SELECT, INSERT ON gov.incident_events, gov.decisions, gov.access_reviews TO envirosense_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA gov TO envirosense_app;
"""


def _risks(c):
    path = GOVERNANCE / "risk_register.csv"
    if not path.exists():
        return
    for r in csv.DictReader(path.open()):
        controls = [x.strip() for x in r.get("controls_in_place", "").split(";") if x.strip()]
        status = {"open": "open", "reduced": "reduced", "acceptable for a research prototype": "accepted", "accepted": "accepted", "closed": "closed"}.get(
            (r.get("status") or "open").strip().lower(), "open")
        c.execute(sa.text("INSERT INTO gov.risks (id, stage, risk, cause, likelihood, severity, controls, planned, owner, residual, status, next_review) "
                          "VALUES (:i, :st, :r, :c, :l, :s, :ctl, :p, :o, :res, :status, current_date + 90) ON CONFLICT (id) DO NOTHING"),
                  dict(i=r["id"], st=r["stage"], r=r["harm_or_risk"], c=r.get("cause", ""), l=int(r["likelihood_1to5"]), s=int(r["severity_1to5"]),
                       ctl=controls, p=r.get("controls_planned", ""), o=r.get("owner") or "PI", res=r.get("residual_note", ""), status=status))


def _decisions(c):
    """The decision log kept so far as a markdown table becomes the first rows of gov.decisions (kind 'imported'), with its dates."""
    path = GOVERNANCE / "decision_log.md"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0][:4].isdigit():
            continue
        c.execute(sa.text("INSERT INTO gov.decisions (at, kind, decision, reason, decided_by, approved_by, ref) "
                          "VALUES (CAST(:d AS date), 'imported', :x, :r, :b, NULLIF(:a, ''), 'governance/decision_log.md')"),
                  dict(d=cells[0][:10], x=cells[1], r=cells[2] if len(cells[2]) >= 5 else "(no reason given)", b=cells[3] or "unknown",
                       a=cells[4] if len(cells) > 4 else ""))


def upgrade():
    c = op.get_bind()
    c.exec_driver_sql(DDL)
    _decisions(c)
    for key, desc, sens in PERMISSIONS:
        c.execute(sa.text("INSERT INTO iam.permissions (key, description, sensitive) VALUES (:k, :d, :s)"), dict(k=key, d=desc, s=sens))
    c.exec_driver_sql("ALTER TABLE iam.role_permissions DISABLE TRIGGER builtin_role_permissions_fixed")   # built-in roles change only by migration
    for role, perm in GRANTS:
        c.execute(sa.text("INSERT INTO iam.role_permissions (role_key, permission_key) VALUES (:r, :p)"), dict(r=role, p=perm))
    c.exec_driver_sql("ALTER TABLE iam.role_permissions ENABLE TRIGGER builtin_role_permissions_fixed")
    for key, value, note in THRESHOLDS:
        c.execute(sa.text("INSERT INTO sem.thresholds (key, value, set_by, decision_ref, note) VALUES (:k, :v, 'migration', 'migration 0007', :n)"),
                  dict(k=key, v=value, n=note))
    pos, m, p, perm = REPORT_RULE
    c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=pos, m=m, p=p, x=perm))
    start = c.execute(sa.text("SELECT max(position) FROM iam.route_policy")).scalar()
    for i, (m, p, perm) in enumerate(RULES, start + 1):
        c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=i, m=m, p=p, x=perm))
    _risks(c)


def downgrade():
    c = op.get_bind()
    c.exec_driver_sql("DELETE FROM iam.route_policy WHERE path LIKE '/api/gov/%%' OR position = 0")
    c.exec_driver_sql("ALTER TABLE iam.role_permissions DISABLE TRIGGER builtin_role_permissions_fixed")
    c.exec_driver_sql("DELETE FROM iam.role_permissions WHERE permission_key IN ('incident_manage', 'risk_manage')")
    c.exec_driver_sql("ALTER TABLE iam.role_permissions ENABLE TRIGGER builtin_role_permissions_fixed")
    c.exec_driver_sql("DELETE FROM iam.permissions WHERE key IN ('incident_manage', 'risk_manage')")
    c.exec_driver_sql("DROP TRIGGER thresholds_fixed ON sem.thresholds")
    c.exec_driver_sql("DELETE FROM sem.thresholds WHERE decision_ref = 'migration 0007'")
    c.exec_driver_sql("ALTER TABLE wf.alert_review_events DROP COLUMN seconds_to_decide, DROP COLUMN evidence_viewed")
    c.exec_driver_sql("ALTER TABLE iam.users DROP COLUMN totp_secret, DROP COLUMN totp_enabled_at")
    c.exec_driver_sql("DELETE FROM iam.route_policy WHERE path LIKE '/api/auth/two-step/%%'")
    c.exec_driver_sql("ALTER TABLE core.assessments DROP COLUMN abstained, DROP COLUMN abstain_reasons, DROP COLUMN rule_version")
    c.exec_driver_sql("ALTER TABLE ingest.uploads DROP COLUMN source, DROP COLUMN licence, DROP COLUMN rights_confirmed_by, DROP COLUMN input_quality")
    c.exec_driver_sql("DROP SCHEMA gov CASCADE")
