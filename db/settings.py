"""Where the database is. Connection strings come from the environment; for convenience on the server they are also read from
<project>/.env.db (written by scripts/db_bootstrap.sh, mode 600). Nothing here is ever logged.

  DATABASE_URL          the running app (role envirosense_app: reads and writes rows, cannot change the schema)
  DATABASE_MIGRATE_URL  migrations and backups (role envirosense_owner)
  ENVIROSENSE_TEST_DB=1 use TEST_DATABASE_URL / TEST_DATABASE_MIGRATE_URL instead (the test suite sets this)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env.db"


def _env_file() -> dict:
    out = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def url(role: str = "app") -> str:
    prefix = "TEST_" if os.environ.get("ENVIROSENSE_TEST_DB") == "1" else ""
    key = prefix + ("DATABASE_URL" if role == "app" else "DATABASE_MIGRATE_URL")
    val = os.environ.get(key) or _env_file().get(key)
    if not val:
        raise RuntimeError(f"{key} is not set (environment or {ENV_FILE}); run scripts/db_bootstrap.sh on the server")
    return val
