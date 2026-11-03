"""Approval requests: a change to the approved model, a threshold or a role's permissions is applied only when a different eligible person approves

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

POLICY = [
    ("model_approval", "model_approve", 7, "Change the approved default model"),
    ("threshold_change", "model_approve", 7, "Change a threshold that alters what the application flags (review confidence)"),
    ("role_permissions", "users", 7, "Change the permissions of a custom role"),
]
RULES = [("GET", "/api/approvals", "any"), ("POST", "/api/approvals/[^/]+/(approve|reject|withdraw)", "any")]

DDL = """
CREATE TABLE wf.approval_policy (
  kind                text PRIMARY KEY,
  approver_permission text NOT NULL REFERENCES iam.permissions (key),
  ttl_days            integer NOT NULL DEFAULT 7 CHECK (ttl_days > 0),
  description         text NOT NULL
);

CREATE TABLE wf.approval_requests (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind           text NOT NULL REFERENCES wf.approval_policy (kind),
  subject        text NOT NULL,
  payload        jsonb NOT NULL,
  state          text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'approved', 'rejected', 'withdrawn', 'expired', 'failed')),
  requested_by   text NOT NULL,
  requested_unit text,
  requested_at   timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL,
  decided_by     text,
  decided_at     timestamptz,
  decision_note  text,
  self_approved  boolean NOT NULL DEFAULT false,
  outcome        jsonb,
  -- the two-person rule: the one who decides is not the one who asked, unless nobody else is eligible (checked by a trigger below)
  CONSTRAINT second_person CHECK (state NOT IN ('approved', 'rejected', 'failed') OR (decided_by IS NOT NULL AND (decided_by <> requested_by OR self_approved))),
  CONSTRAINT self_only_when_applied CHECK (NOT self_approved OR state IN ('approved', 'failed')),
  CONSTRAINT rejection_needs_reason CHECK (state <> 'rejected' OR char_length(btrim(coalesce(decision_note, ''))) >= 5)
);
CREATE UNIQUE INDEX approval_one_pending ON wf.approval_requests (kind, subject) WHERE state = 'pending';
CREATE INDEX approval_state ON wf.approval_requests (state, requested_at DESC);

-- a decided request is a record: it cannot be edited
CREATE FUNCTION wf.approval_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state <> 'pending' THEN
    RAISE EXCEPTION 'a decided approval request cannot be changed' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_fixed BEFORE UPDATE ON wf.approval_requests FOR EACH ROW EXECUTE FUNCTION wf.approval_fixed();

-- self-approval is allowed only when no other active user holds the approving permission
CREATE FUNCTION wf.approval_self_ok() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE perm text;
BEGIN
  IF NEW.self_approved THEN
    SELECT approver_permission INTO perm FROM wf.approval_policy WHERE kind = NEW.kind;
    IF EXISTS (SELECT 1 FROM iam.users u JOIN iam.role_permissions rp ON rp.role_key = u.role
               WHERE u.active AND rp.permission_key = perm AND u.username <> NEW.requested_by) THEN
      RAISE EXCEPTION 'another eligible approver exists; this change needs their approval' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_self_ok BEFORE INSERT OR UPDATE ON wf.approval_requests FOR EACH ROW EXECUTE FUNCTION wf.approval_self_ok();

GRANT SELECT ON wf.approval_policy TO envirosense_app;
GRANT SELECT, INSERT, UPDATE ON wf.approval_requests TO envirosense_app;
"""


def upgrade():
    c = op.get_bind()
    c.exec_driver_sql(DDL)
    for kind, perm, days, desc in POLICY:
        c.execute(sa.text("INSERT INTO wf.approval_policy VALUES (:k, :p, :d, :t)"), dict(k=kind, p=perm, d=days, t=desc))
    start = c.execute(sa.text("SELECT max(position) FROM iam.route_policy")).scalar()
    for i, (m, p, perm) in enumerate(RULES, start + 1):
        c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=i, m=m, p=p, x=perm))


def downgrade():
    c = op.get_bind()
    c.exec_driver_sql("DELETE FROM iam.route_policy WHERE path LIKE '/api/approvals%%'")
    c.exec_driver_sql("DROP TABLE wf.approval_requests, wf.approval_policy CASCADE")
    c.exec_driver_sql("DROP FUNCTION wf.approval_fixed(), wf.approval_self_ok()")
