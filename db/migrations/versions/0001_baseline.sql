-- EnviroSense baseline schema. Reference data (classes, metrics, glossary, thresholds) is in 0002.
-- Schemas: iam (accounts), audit (append-only record), sem (semantic layer), ingest (uploads and their jobs),
--          core (assessments and alerts, with PostGIS geometry), wf (review workflow).

CREATE SCHEMA iam;
CREATE SCHEMA audit;
CREATE SCHEMA sem;
CREATE SCHEMA ingest;
CREATE SCHEMA core;
CREATE SCHEMA wf;

-- ======================================================================================================== iam

CREATE TABLE iam.units (
  id          text PRIMARY KEY,
  name        text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 2 AND 80),
  parent_id   text REFERENCES iam.units (id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  text NOT NULL DEFAULT 'system'
);
CREATE UNIQUE INDEX units_sibling_name ON iam.units (COALESCE(parent_id, ''), lower(btrim(name)));
CREATE UNIQUE INDEX units_single_root  ON iam.units ((true)) WHERE parent_id IS NULL;
CREATE INDEX units_parent ON iam.units (parent_id);

CREATE FUNCTION iam.units_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.parent_id IS NULL AND NEW.parent_id IS NOT NULL THEN
    RAISE EXCEPTION 'the top unit cannot be moved' USING ERRCODE = '23514';
  END IF;
  IF NEW.parent_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.parent_id IS DISTINCT FROM OLD.parent_id) THEN
    IF NEW.parent_id = NEW.id OR EXISTS (
         WITH RECURSIVE up AS (
           SELECT id, parent_id FROM iam.units WHERE id = NEW.parent_id
           UNION
           SELECT u.id, u.parent_id FROM iam.units u JOIN up ON u.id = up.parent_id)
         SELECT 1 FROM up WHERE id = NEW.id) THEN
      RAISE EXCEPTION 'a unit cannot move under itself or one of its own sub-units' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER units_guard BEFORE INSERT OR UPDATE ON iam.units FOR EACH ROW EXECUTE FUNCTION iam.units_guard();

CREATE TABLE iam.users (
  username         text PRIMARY KEY CHECK (username ~ '^[a-z0-9._-]{3,32}$'),
  full_name        text NOT NULL CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 80),
  role             text NOT NULL CHECK (role IN ('admin', 'analyst', 'officer', 'auditor')),
  unit_id          text NOT NULL REFERENCES iam.units (id),
  pw_hash          text NOT NULL,
  active           boolean NOT NULL DEFAULT true,
  must_change      boolean NOT NULL DEFAULT true,
  last_login_at    timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  created_by       text NOT NULL DEFAULT 'system',
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_unit ON iam.users (unit_id);

-- there is always at least one active administrator (checked at the end of the statement that would remove the last one)
CREATE FUNCTION iam.require_admin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM iam.users WHERE role = 'admin' AND active) THEN
    RAISE EXCEPTION 'there must be at least one active administrator' USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER users_require_admin AFTER UPDATE OR DELETE ON iam.users
  DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION iam.require_admin();

-- failed sign-ins are counted per name, whether or not the account exists, so a lock does not reveal which names are real
CREATE TABLE iam.login_throttle (
  username         text PRIMARY KEY,
  failed_attempts  integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until     timestamptz
);

-- server-side sessions: signing out or changing a password revokes them immediately
CREATE TABLE iam.sessions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username    text NOT NULL REFERENCES iam.users (username) ON UPDATE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  revoked_at  timestamptz,
  client      text
);
CREATE INDEX sessions_live ON iam.sessions (username) WHERE revoked_at IS NULL;

-- ===================================================================================================== audit

CREATE TABLE audit.log (
  seq         bigint PRIMARY KEY CHECK (seq > 0),
  utc         timestamptz NOT NULL,
  action      text NOT NULL,
  actor       text NOT NULL,
  assessment  text,
  detail      json NOT NULL DEFAULT '{}',   -- json, not jsonb: the exact text is what the hash covers
  actor_unit  text,
  actor_role  text,
  prev        char(64) NOT NULL,
  hash        char(64) NOT NULL UNIQUE
);
CREATE INDEX audit_assessment  ON audit.log (assessment) WHERE assessment IS NOT NULL;
CREATE INDEX audit_action_time ON audit.log (action, utc DESC);
CREATE INDEX audit_actor       ON audit.log (actor, utc DESC);
CREATE INDEX audit_unit        ON audit.log (actor_unit);

CREATE FUNCTION audit.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'the audit log is append-only' USING ERRCODE = '42501';
END $$;
CREATE TRIGGER audit_no_update   BEFORE UPDATE OR DELETE ON audit.log FOR EACH ROW EXECUTE FUNCTION audit.refuse_change();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit.log FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_change();

-- every new entry must follow the last one (seq + 1, prev = last hash); writers are serialised by an advisory lock
CREATE FUNCTION audit.check_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE last_seq bigint; last_hash text;
BEGIN
  PERFORM pg_advisory_xact_lock(727001);
  SELECT seq, hash INTO last_seq, last_hash FROM audit.log ORDER BY seq DESC LIMIT 1;
  IF NOT FOUND THEN last_seq := 0; last_hash := repeat('0', 64); END IF;
  IF NEW.seq <> last_seq + 1 OR NEW.prev <> last_hash THEN
    RAISE EXCEPTION 'audit chain: the entry does not follow the last one' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER audit_chain BEFORE INSERT ON audit.log FOR EACH ROW EXECUTE FUNCTION audit.check_link();

-- ======================================================================================================= sem

CREATE TABLE sem.damage_classes (
  code        smallint PRIMARY KEY CHECK (code BETWEEN 0 AND 3),
  key         text NOT NULL UNIQUE,
  label       text NOT NULL,
  colour      text NOT NULL,
  severe      boolean NOT NULL DEFAULT false,
  definition  text NOT NULL
);

CREATE TABLE sem.metrics (
  key             text NOT NULL,
  version         integer NOT NULL CHECK (version > 0),
  name            text NOT NULL,
  description     text NOT NULL,
  formula         text NOT NULL,
  unit            text,
  status          text NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
  owner           text NOT NULL,
  effective_from  date NOT NULL,
  source_ref      text,
  PRIMARY KEY (key, version)
);
CREATE UNIQUE INDEX metrics_one_active ON sem.metrics (key) WHERE status = 'active';

CREATE TABLE sem.glossary (
  term        text PRIMARY KEY,
  kind        text NOT NULL CHECK (kind IN ('entity', 'rule', 'measure', 'term')),
  definition  text NOT NULL,
  see_also    text[] NOT NULL DEFAULT '{}',
  source_ref  text
);

CREATE TABLE sem.model_versions (
  id                 text PRIMARY KEY,
  label              text NOT NULL,
  kind               text NOT NULL CHECK (kind IN ('unet', 'classifier')),
  run_name           text,
  checkpoint_sha256  text,
  architecture       text,
  trained_on         text,
  metrics            jsonb NOT NULL DEFAULT '{}',
  status             text NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'approved', 'retired')),
  approved_by        text,
  approved_at        timestamptz,
  decision_ref       text,
  approval_reason    text,
  previous_model     text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT approval_has_approver CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX model_one_approved ON sem.model_versions ((true)) WHERE status = 'approved';

CREATE TABLE sem.thresholds (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  key             text NOT NULL,
  value           numeric NOT NULL,
  effective_from  timestamptz NOT NULL DEFAULT now(),
  set_by          text NOT NULL,
  decision_ref    text,
  note            text
);
CREATE INDEX thresholds_current ON sem.thresholds (key, effective_from DESC, id DESC);

-- ==================================================================================================== ingest

CREATE TABLE ingest.uploads (
  id            text PRIMARY KEY CHECK (id ~ '^upl_[0-9a-f]{8}$'),
  unit_id       text NOT NULL REFERENCES iam.units (id),
  created_by    text NOT NULL,
  name          text NOT NULL,
  disaster_type text NOT NULL,
  event_date    date,
  model_id      text,
  after_file    text NOT NULL,
  before_file   text,
  after_bounds  jsonb,
  before_bounds jsonb,
  meta          jsonb NOT NULL DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX uploads_unit ON ingest.uploads (unit_id, created_at DESC);

-- a job is one run of the pipeline for an upload; a worker claims it with FOR UPDATE SKIP LOCKED, keeps a heartbeat,
-- and a job whose worker died is queued again (up to max_attempts) instead of being lost
CREATE TABLE ingest.jobs (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind          text NOT NULL DEFAULT 'assess_upload',
  upload_id     text NOT NULL REFERENCES ingest.uploads (id) ON DELETE CASCADE,
  state         text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  step          text NOT NULL DEFAULT '',
  priority      integer NOT NULL DEFAULT 0,
  attempts      integer NOT NULL DEFAULT 0,
  max_attempts  integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
  run_after     timestamptz NOT NULL DEFAULT now(),
  locked_by     text,
  heartbeat_at  timestamptz,
  error         text,
  error_detail  text,
  result        jsonb NOT NULL DEFAULT '{}',
  notes         jsonb NOT NULL DEFAULT '[]',
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    text,
  started_at    timestamptz,
  finished_at   timestamptz
);
CREATE INDEX jobs_queue  ON ingest.jobs (priority DESC, run_after, id) WHERE state = 'queued';
CREATE INDEX jobs_upload ON ingest.jobs (upload_id, id DESC);
CREATE UNIQUE INDEX jobs_one_active_per_upload ON ingest.jobs (upload_id) WHERE state IN ('queued', 'running');

CREATE TABLE ingest.job_steps (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id       bigint NOT NULL REFERENCES ingest.jobs (id) ON DELETE CASCADE,
  seq          integer NOT NULL,
  name         text NOT NULL,
  state        text NOT NULL CHECK (state IN ('running', 'ok', 'failed')),
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  detail       jsonb NOT NULL DEFAULT '{}',
  UNIQUE (job_id, seq)
);

-- ======================================================================================================= core

-- an assessment is the model's result for one scene, upload or area; the full record (structures, outlines, provenance)
-- stays in the record file (large and derived), the database holds what is queried, scoped, reviewed and traced
CREATE TABLE core.assessments (
  id                text PRIMARY KEY,
  kind              text NOT NULL CHECK (kind IN ('benchmark', 'upload', 'area', 'event')),
  upload_id         text REFERENCES ingest.uploads (id) ON DELETE CASCADE,
  scene             text,
  model_id          text NOT NULL,
  model_version_id  text REFERENCES sem.model_versions (id),
  record_path       text NOT NULL,
  record_sha256     text,
  thresholds        jsonb NOT NULL DEFAULT '{}',
  provenance        jsonb NOT NULL DEFAULT '{}',
  n_alerts          integer NOT NULL DEFAULT 0,
  footprint         geometry(Polygon, 4326),
  created_at        timestamptz NOT NULL DEFAULT now(),
  created_by        text
);
CREATE INDEX assessments_upload    ON core.assessments (upload_id);
CREATE INDEX assessments_footprint ON core.assessments USING gist (footprint);

CREATE TABLE core.alerts (
  assessment_id     text NOT NULL REFERENCES core.assessments (id) ON DELETE CASCADE,
  alert_id          text NOT NULL,
  severity          text NOT NULL CHECK (severity IN ('high', 'medium')),
  priority          numeric,
  severe_share      numeric,
  area_m2           numeric,
  structures        integer,
  severe_structures integer,
  geom              geometry(Polygon, 4326),
  props             jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (assessment_id, alert_id)
);
CREATE INDEX alerts_geom ON core.alerts USING gist (geom);

-- ========================================================================================================= wf

CREATE TABLE wf.alert_reviews (
  assessment_id  text NOT NULL,
  alert_id       text NOT NULL,
  status         text NOT NULL CHECK (status IN ('pending', 'proposed', 'confirmed', 'dismissed', 'needs_info', 'retracted')),
  note           text NOT NULL DEFAULT '' CHECK (char_length(note) <= 500),
  reviewed_by    text,
  reviewed_at    timestamptz,
  proposed_by    text,
  version        integer NOT NULL DEFAULT 1,
  PRIMARY KEY (assessment_id, alert_id),
  FOREIGN KEY (assessment_id, alert_id) REFERENCES core.alerts (assessment_id, alert_id) ON DELETE CASCADE,
  -- the four-eyes rule, held by the database as well as by the application
  CONSTRAINT four_eyes CHECK (status <> 'confirmed' OR (proposed_by IS NOT NULL AND reviewed_by IS DISTINCT FROM proposed_by)),
  CONSTRAINT reason_required CHECK (status NOT IN ('dismissed', 'retracted') OR char_length(btrim(note)) > 0)
);
CREATE INDEX reviews_status ON wf.alert_reviews (status);

CREATE TABLE wf.alert_review_events (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  assessment_id  text NOT NULL,
  alert_id       text NOT NULL,
  seq            integer NOT NULL,
  status         text NOT NULL CHECK (status IN ('pending', 'proposed', 'confirmed', 'dismissed', 'needs_info', 'retracted')),
  note           text NOT NULL DEFAULT '',
  actor          text NOT NULL,
  role           text NOT NULL,
  unit_id        text,
  at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assessment_id, alert_id, seq),
  FOREIGN KEY (assessment_id, alert_id) REFERENCES core.alerts (assessment_id, alert_id) ON DELETE CASCADE
);
CREATE FUNCTION wf.events_no_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'review history cannot be edited' USING ERRCODE = '42501';
END $$;
CREATE TRIGGER events_no_update BEFORE UPDATE ON wf.alert_review_events FOR EACH ROW EXECUTE FUNCTION wf.events_no_update();

-- ==================================================================================================== grants
-- the running app is envirosense_app: it reads and writes rows and nothing else (no DDL, no change to the audit log)

GRANT USAGE ON SCHEMA iam, audit, sem, ingest, core, wf TO envirosense_app;
GRANT SELECT, INSERT, UPDATE ON iam.units, iam.users TO envirosense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON iam.sessions, iam.login_throttle TO envirosense_app;
GRANT SELECT, INSERT ON audit.log TO envirosense_app;
GRANT SELECT ON sem.damage_classes, sem.metrics, sem.glossary TO envirosense_app;
GRANT SELECT, INSERT, UPDATE ON sem.model_versions TO envirosense_app;
GRANT SELECT, INSERT ON sem.thresholds TO envirosense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ingest.uploads, ingest.jobs, ingest.job_steps TO envirosense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.assessments, core.alerts TO envirosense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON wf.alert_reviews TO envirosense_app;
GRANT SELECT, INSERT, DELETE ON wf.alert_review_events TO envirosense_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ingest, sem, wf TO envirosense_app;
