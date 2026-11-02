"""Create a demonstration organisation: a national authority, two provincial departments, a district team, and one user per role.

  uv run --no-sync python app/scripts/seed_demo_accounts.py

Run it after the app has started once (it creates the top unit and the first administrator). Passwords are generated and written to
runs/app/auth/demo_accounts.txt (mode 600); every demo user must change theirs at first sign-in. Safe to run twice: existing names are kept.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.api import auth  # noqa: E402

TREE = [("Sindh provincial disaster management", None), ("Karachi district team", "Sindh provincial disaster management"),
        ("Punjab provincial disaster management", None)]
USERS = [  # username, full name, role, unit
    ("nda.admin", "National administrator", "admin", None),
    ("nda.auditor", "National auditor", "auditor", None),
    ("nda.officer", "National approving officer", "officer", None),
    ("sindh.officer", "Sindh approving officer", "officer", "Sindh provincial disaster management"),
    ("karachi.analyst1", "Karachi analyst one", "analyst", "Karachi district team"),
    ("karachi.analyst2", "Karachi analyst two", "analyst", "Karachi district team"),
    ("punjab.officer", "Punjab approving officer", "officer", "Punjab provincial disaster management"),
]


def main():
    auth.bootstrap()
    units = auth.units()
    top = next(k for k, v in units.items() if v.get("parent") is None)
    by_name = {v["name"]: k for k, v in units.items()}
    for name, parent in TREE:
        if name not in by_name:
            by_name[name] = auth.create_unit(name, by_name[parent] if parent else top, "seed")["id"]
    lines = []
    for username, full, role, unit in USERS:
        if username in auth.users():
            continue
        pw = auth.temp_password() + "Aa1"
        auth.create_user(username, full, role, by_name[unit] if unit else top, pw, "seed")
        lines.append(f"{username:18} {role:8} {pw}")
    if lines:
        out = auth.DIR / "demo_accounts.txt"
        out.write_text("username           role     temporary password (change at first sign-in)\n" + "\n".join(lines) + "\n")
        os.chmod(out, 0o600)
        print(f"{len(lines)} users created; passwords in {out}")
    else:
        print("nothing to create")


if __name__ == "__main__":
    main()
