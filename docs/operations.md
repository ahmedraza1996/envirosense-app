# Operating the application database

PostgreSQL 17 with PostGIS runs as the system service on the server (`pg_lsclusters`), listening on 127.0.0.1:5432 only. Everything the application
keeps, except imagery files and the large assessment records, is in the database `envirosense`.

## What is where

| Schema | Holds | Written by |
| --- | --- | --- |
| `iam` | units (tree), users, sessions, sign-in throttling | `api/auth.py` |
| `audit` | `log`: append-only, hash-chained | `api/audit.py` |
| `sem` | damage classes, metric definitions, glossary, model versions, thresholds | migrations; `db/semantic.py` |
| `ingest` | uploads, jobs (queue with retries), job steps | `api/uploads.py` |
| `core` | assessments and alerts (PostGIS outlines) | `api/registry.py` |
| `wf` | alert reviews and their immutable history | `api/reviews.py` |

Files that stay on disk: the uploaded images and aligned JPEGs (`runs/app/uploads/<id>/`), the assessment records and damage maps (`runs/app/assessments/`),
and the caches. The database refers to them; deleting an upload removes both.

## Roles and configuration

- `envirosense_owner` owns the schema and runs migrations and backups. `envirosense_app` is what the running app uses: it reads and writes rows, cannot
  change the schema, and cannot update or delete audit rows or review history.
- Connection strings: `DATABASE_URL` (app) and `DATABASE_MIGRATE_URL` (owner), from the environment or `~/envirosense/.env.db` (mode 600, written by
  `scripts/db_bootstrap.sh`). The session signing key is `ENVIROSENSE_SECRET_KEY` (hex) or `runs/app/auth/secret.key`.
- One-time set-up on a new server: install `postgresql-17 postgresql-17-postgis-3`, run `sudo sh scripts/db_bootstrap.sh`, then
  `cd app && alembic -c alembic.ini upgrade head` with `DATABASE_MIGRATE_URL` set. Data from the file-based version: `python -m app.scripts.db_import_files --apply`.

## Migrations

The schema is SQL in `db/migrations/versions/`. Change it by adding a new revision (`alembic -c alembic.ini revision -m "what"`), never by editing an applied one.
The test suite builds the schema from scratch with `downgrade base` then `upgrade head` on `envirosense_test`, so a migration that cannot go both ways fails the tests.

## Backups

`sh scripts/db_backup.sh` writes a compressed dump to `runs/backups/` (keeps the newest 14) and lists it to prove it is readable. `sh scripts/db_restore_check.sh`
restores the newest dump into the test database and compares row counts with the live database. To run it nightly add to the crontab of the project user:

    30 2 * * *  cd $HOME/envirosense && sh scripts/db_backup.sh >> runs/logs/db_backup.log 2>&1

Limits to know: the backups sit on the same disk as the database, so copy `runs/backups/` to another machine or storage as well; imagery and assessment records
are not in the dump (they are files and need their own copy); point-in-time recovery (WAL archiving) is not configured.

## Audit chain

Each audit row carries the hash of the one before. The application's role cannot update or delete rows and the database refuses a row that does not follow the last
one. Someone with administrator rights on the database server could still rewrite the whole chain. To make that detectable, write down the chain head from time to time
in a place the server does not control (the decision log, an email to the supervisor):

    psql "$DATABASE_MIGRATE_URL" -c "select seq, hash from audit.log order by seq desc limit 1"

`GET /api/audit/verify` walks the chain; it matches the written-down head only if the number of entries has not been cut back.

## Ingestion jobs

An upload creates a row in `ingest.jobs`. A worker thread in each app process claims one job at a time (`FOR UPDATE SKIP LOCKED`), beats a heartbeat every 20 s and records
each step in `ingest.job_steps`. A job whose heartbeat is older than 120 s (the process died or the server restarted) goes back to the queue, up to `max_attempts` (3),
then fails with a message. A pipeline error (bad image, no coverage) fails the job at once and is not retried. `GET /api/jobs` lists jobs and steps for the caller's unit tree.

## Semantic layer

`GET /api/semantic/{classes,metrics,glossary,models,thresholds}` serve the governed definitions. The review confidence threshold is read from `sem.thresholds` (cached for 30 s);
an administrator changes it with `PUT /api/admin/thresholds/review_confidence` (value and reason), which keeps the old value in the history and writes the audit log. The approved
default model is the one `sem.model_versions` row with status `approved` (the database allows only one).
