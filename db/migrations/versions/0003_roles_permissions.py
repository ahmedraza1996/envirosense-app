"""Roles, permissions and the route policy as data (iam.roles, iam.permissions, iam.role_permissions, iam.permission_conflicts, iam.route_policy)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("users", "Manage users and units in the own unit tree", True),
    ("audit", "Read the audit log and verify its chain", True),
    ("model_approve", "Set the approved default model and the review threshold", True),
    ("view", "See scenes, models, uploads, assessments and maps", False),
    ("assess", "Run the model on a scene or an area", False),
    ("upload", "Upload imagery and edit its details", False),
    ("delete_own_upload", "Delete an upload the user made", False),
    ("review", "Propose, dismiss or ask for information on alerts", False),
    ("review_read", "Read the review history of alerts", False),
    ("geo_offset", "Measure and set the map position offset", False),
    ("approve", "Confirm another person's proposal and retract confirmed alerts", True),
    ("export", "Export alerts and reports", True),
    ("delete_upload", "Delete any upload in the unit tree", True),
]
OPEN = [("any", "Every signed-in user"), ("public", "No sign-in needed")]
ANALYST = {"view", "assess", "upload", "delete_own_upload", "review", "review_read", "geo_offset"}
ROLES = [
    ("admin", "System administrator", "Manages users and units in their unit and below, sets the approved model, reads the audit log. No access to imagery or alerts.",
     {"users", "audit", "model_approve"}),
    ("analyst", "Analyst", "Assesses, uploads, proposes, dismisses and asks for information. Cannot confirm, retract or export.", ANALYST),
    ("officer", "Approving officer", "Everything an analyst does, plus confirms another person's proposal, retracts, exports and deletes uploads in the unit tree.",
     ANALYST | {"approve", "export", "delete_upload"}),
    ("auditor", "Auditor", "Read-only: audit log and review history. No imagery, alert lists or exports.", {"audit", "review_read"}),
]
SEPARATION = [   # (permission, held-together-with, why): no role may hold both
    ("users", ["view", "assess", "upload", "delete_own_upload", "review", "geo_offset", "approve", "export", "delete_upload"], "whoever manages accounts does not also handle imagery or alerts"),
    ("audit", ["assess", "upload", "delete_own_upload", "review", "geo_offset", "approve", "export", "delete_upload", "view"], "the auditor reads the record and does not take part in the work it records"),
]
POLICY = [
    ("GET", "/api/health", "public"), ("POST", "/api/auth/login", "public"), ("POST", "/api/auth/logout", "public"),
    ("GET", "/api/auth/me", "any"), ("POST", "/api/auth/password", "any"), ("GET", "/api/policy", "any"), ("GET", "/api/approved-model", "any"),
    ("GET", "/api/semantic/.*", "any"), ("PUT", "/api/admin/thresholds/[^/]+", "model_approve"), ("GET", "/api/jobs", "view"),
    ("GET", "/api/admin/(users|units)", "users"), ("(POST|PATCH)", "/api/admin/(users|units)(/[^/]+)?", "users"),
    ("POST", "/api/admin/users/[^/]+/reset-password", "users"), ("GET", "/api/admin/(roles|permissions|route-policy)", "users"),
    ("(POST|PUT|DELETE)", "/api/admin/roles(/[^/]+(/permissions)?)?", "users"), ("PUT", "/api/admin/approved-model", "model_approve"),
    ("GET", "/api/audit(/verify)?", "audit"), ("GET", "/api/assessments/[^/]+/reviews", "review_read"),
    ("PUT", "/api/assessments/[^/]+/alerts/[^/]+/review", "review"), ("GET", "/api/assessments/[^/]+/export\\.(geojson|csv)", "export"),
    ("(PUT|POST)", "/api/assessments/[^/]+/geo-offset(/measure)?", "geo_offset"), ("(POST)", "/api/(assess|assess-area)", "assess"),
    ("POST", "/api/events/[^/]+/assess", "assess"), ("POST", "/api/uploads", "upload"), ("PATCH", "/api/uploads/[^/]+", "upload"),
    ("DELETE", "/api/uploads/[^/]+", "delete_own_upload"), ("GET", "/api/(models|scenes|uploads|events|assessments)(/.*)?", "view"),
]

DDL = """
CREATE TABLE iam.permissions (
  key          text PRIMARY KEY CHECK (key ~ '^[a-z_]+$'),
  description  text NOT NULL,
  assignable   boolean NOT NULL DEFAULT true,       -- false: 'any' and 'public' are route rules, not something a role holds
  sensitive    boolean NOT NULL DEFAULT false,
  UNIQUE (key, assignable)
);
CREATE TABLE iam.roles (
  key          text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,31}$'),
  label        text NOT NULL CHECK (char_length(btrim(label)) BETWEEN 2 AND 60),
  description  text NOT NULL DEFAULT '',
  builtin      boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  created_by   text NOT NULL DEFAULT 'system'
);
CREATE TABLE iam.role_permissions (
  role_key        text NOT NULL REFERENCES iam.roles (key) ON UPDATE CASCADE ON DELETE CASCADE,
  permission_key  text NOT NULL,
  assignable      boolean NOT NULL DEFAULT true CHECK (assignable),
  PRIMARY KEY (role_key, permission_key),
  FOREIGN KEY (permission_key, assignable) REFERENCES iam.permissions (key, assignable)
);
CREATE TABLE iam.permission_conflicts (
  a       text NOT NULL REFERENCES iam.permissions (key),
  b       text NOT NULL REFERENCES iam.permissions (key),
  reason  text NOT NULL,
  PRIMARY KEY (a, b),
  CHECK (a < b)
);
-- first matching rule wins; a route without a rule is refused
CREATE TABLE iam.route_policy (
  position    integer PRIMARY KEY,
  method      text NOT NULL,
  path        text NOT NULL,
  permission  text NOT NULL REFERENCES iam.permissions (key)
);

CREATE FUNCTION iam.role_conflicts() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c record;
BEGIN
  SELECT k.a, k.b, k.reason INTO c FROM iam.permission_conflicts k
   WHERE (k.a = NEW.permission_key AND k.b IN (SELECT permission_key FROM iam.role_permissions WHERE role_key = NEW.role_key))
      OR (k.b = NEW.permission_key AND k.a IN (SELECT permission_key FROM iam.role_permissions WHERE role_key = NEW.role_key));
  IF FOUND THEN
    RAISE EXCEPTION 'a role cannot hold both "%%" and "%%": %%', c.a, c.b, c.reason USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER role_conflicts BEFORE INSERT ON iam.role_permissions FOR EACH ROW EXECUTE FUNCTION iam.role_conflicts();

-- built-in roles are fixed; a changed role is a new role based on one of them
CREATE FUNCTION iam.builtin_roles_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r text;
BEGIN
  IF TG_TABLE_NAME = 'roles' THEN
    IF OLD.builtin THEN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a built-in role cannot be deleted' USING ERRCODE = '23514';
      ELSIF NEW.key <> OLD.key OR NOT NEW.builtin THEN
        RAISE EXCEPTION 'a built-in role cannot be renamed or made custom' USING ERRCODE = '23514';
      END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN r := OLD.role_key; ELSE r := NEW.role_key; END IF;
  IF EXISTS (SELECT 1 FROM iam.roles WHERE key = r AND builtin) THEN
    RAISE EXCEPTION 'the permissions of a built-in role cannot be changed; create a role based on it' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER builtin_roles_fixed BEFORE UPDATE OR DELETE ON iam.roles FOR EACH ROW EXECUTE FUNCTION iam.builtin_roles_fixed();
CREATE TRIGGER builtin_role_permissions_fixed BEFORE INSERT OR UPDATE OR DELETE ON iam.role_permissions FOR EACH ROW EXECUTE FUNCTION iam.builtin_roles_fixed();

GRANT SELECT ON iam.permissions, iam.permission_conflicts, iam.route_policy TO envirosense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON iam.roles, iam.role_permissions TO envirosense_app;
"""


def upgrade():
    c = op.get_bind()
    c.exec_driver_sql(DDL)
    for key, desc, sens in PERMISSIONS:
        c.execute(sa.text("INSERT INTO iam.permissions (key, description, sensitive) VALUES (:k, :d, :s)"), dict(k=key, d=desc, s=sens))
    for key, desc in OPEN:
        c.execute(sa.text("INSERT INTO iam.permissions (key, description, assignable) VALUES (:k, :d, false)"), dict(k=key, d=desc))
    for a, others, why in SEPARATION:
        for b in others:
            x, y = sorted((a, b))
            c.execute(sa.text("INSERT INTO iam.permission_conflicts VALUES (:a, :b, :r) ON CONFLICT DO NOTHING"), dict(a=x, b=y, r=why))
    for key, label, desc, perms in ROLES:      # inserted as custom, then fixed: the guard is on built-in roles
        c.execute(sa.text("INSERT INTO iam.roles (key, label, description) VALUES (:k, :l, :d)"), dict(k=key, l=label, d=desc))
        for p in sorted(perms):
            c.execute(sa.text("INSERT INTO iam.role_permissions (role_key, permission_key) VALUES (:r, :p)"), dict(r=key, p=p))
    c.exec_driver_sql("UPDATE iam.roles SET builtin = true")
    for i, (m, p, perm) in enumerate(POLICY, 1):
        c.execute(sa.text("INSERT INTO iam.route_policy VALUES (:i, :m, :p, :x)"), dict(i=i, m=m, p=p, x=perm))
    # users now point at roles instead of a fixed list
    c.exec_driver_sql("ALTER TABLE iam.users DROP CONSTRAINT IF EXISTS users_role_check")
    c.exec_driver_sql("ALTER TABLE iam.users ADD CONSTRAINT users_role_fk FOREIGN KEY (role) REFERENCES iam.roles (key) ON UPDATE CASCADE")


def downgrade():
    c = op.get_bind()
    c.exec_driver_sql("ALTER TABLE iam.users DROP CONSTRAINT users_role_fk")
    c.exec_driver_sql("ALTER TABLE iam.users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'analyst', 'officer', 'auditor'))")
    c.exec_driver_sql("DROP TABLE iam.route_policy, iam.permission_conflicts, iam.role_permissions, iam.roles, iam.permissions CASCADE")
    c.exec_driver_sql("DROP FUNCTION iam.role_conflicts(), iam.builtin_roles_fixed()")
