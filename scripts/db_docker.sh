#!/bin/sh
# Database for the app on any machine with Docker (laptop or server; no system install, no sudo). From the project root:  sh app/scripts/db_docker.sh
# Starts PostgreSQL 17 + PostGIS in the container "envirosense-db" on 127.0.0.1:5432 (data kept in the Docker volume envirosense-db), creates the
# same databases, roles and extensions as scripts/db_bootstrap.sh does on the server, and writes the connection strings to .env.db.
# Safe to run again: an existing container, volume and .env.db are kept. Other port: ENVIROSENSE_DB_PORT=5433 sh app/scripts/db_docker.sh
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
ENVF="$root/.env.db"
NAME=envirosense-db
PORT="${ENVIROSENSE_DB_PORT:-5432}"
command -v docker >/dev/null || { echo "Install Docker Desktop first: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running: start Docker Desktop and try again"; exit 1; }

if [ -f "$ENVF" ]; then
  echo "$ENVF exists: keeping the passwords in it"
  OWNER_PW="$(sed -n 's/^DATABASE_MIGRATE_URL=postgresql+psycopg:\/\/envirosense_owner:\([^@]*\)@.*/\1/p' "$ENVF")"
  APP_PW="$(sed -n 's/^DATABASE_URL=postgresql+psycopg:\/\/envirosense_app:\([^@]*\)@.*/\1/p' "$ENVF")"
else
  OWNER_PW="$(openssl rand -hex 24)"
  APP_PW="$(openssl rand -hex 24)"
fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  # the PostGIS image is built for x86-64; Docker Desktop runs it on Apple silicon too
  docker run -d --name "$NAME" --platform linux/amd64 --restart unless-stopped -p "127.0.0.1:$PORT:5432" \
    -e POSTGRES_PASSWORD="$(openssl rand -hex 24)" -v envirosense-db:/var/lib/postgresql/data postgis/postgis:17-3.5 >/dev/null
fi
docker start "$NAME" >/dev/null
printf "waiting for the database"
until docker exec "$NAME" psql -U postgres -h 127.0.0.1 -qtAc "SELECT 1" >/dev/null 2>&1; do printf "."; sleep 2; done   # TCP: only the final server, not the init one
echo " ready"
PSQL="docker exec -i $NAME psql -U postgres -v ON_ERROR_STOP=1 -qtA"

$PSQL postgres <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'envirosense_owner') THEN CREATE ROLE envirosense_owner LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'envirosense_app') THEN CREATE ROLE envirosense_app LOGIN; END IF;
END \$\$;
ALTER ROLE envirosense_owner PASSWORD '$OWNER_PW';
ALTER ROLE envirosense_app PASSWORD '$APP_PW';
SQL
for DB in envirosense envirosense_test; do
  $PSQL postgres -c "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 || \
    $PSQL postgres -c "CREATE DATABASE $DB OWNER envirosense_owner ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8'"
  $PSQL $DB <<SQL
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
REVOKE ALL ON DATABASE $DB FROM PUBLIC;
GRANT CONNECT ON DATABASE $DB TO envirosense_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO envirosense_app;
SQL
done

umask 077
cat > "$ENVF" <<ENV
DATABASE_URL=postgresql+psycopg://envirosense_app:$APP_PW@127.0.0.1:$PORT/envirosense
DATABASE_MIGRATE_URL=postgresql+psycopg://envirosense_owner:$OWNER_PW@127.0.0.1:$PORT/envirosense
TEST_DATABASE_URL=postgresql+psycopg://envirosense_app:$APP_PW@127.0.0.1:$PORT/envirosense_test
TEST_DATABASE_MIGRATE_URL=postgresql+psycopg://envirosense_owner:$OWNER_PW@127.0.0.1:$PORT/envirosense_test
ENV
echo "database ready on 127.0.0.1:$PORT; connection strings in $ENVF"
