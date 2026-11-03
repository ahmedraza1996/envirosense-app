"""Give every account that has never chosen its own password a new temporary password, show the passwords once on this terminal, and delete the plain-text files
they were first written to (runs/app/auth/demo_accounts.txt and first_admin.txt). The passwords are stored nowhere: the database keeps only their hashes.

  ssh -t EnviroSense 'cd ~/envirosense && ~/.local/bin/uv run --no-sync python -m app.scripts.reset_demo_passwords'

Each account must change its password at first sign-in. The reset is written to the audit log.
"""
import sys

from app.api import audit, auth


def main() -> int:
    names = [n for n, u in auth.users().items() if u["active"] and u["must_change"]]
    if not names:
        print("every active account has chosen its own password; nothing to reset")
    new = {}
    for n in names:
        new[n] = auth.temp_password() + "Aa1"
        auth.set_password(n, new[n], True)
        audit.log("password_reset", "system (reset_demo_passwords)", user=n)
    if new:
        print("New temporary passwords (shown once, stored nowhere; change at first sign-in):\n")
        for n, pw in new.items():
            print(f"  {n:22s} {pw}")
    for f in ("demo_accounts.txt", "first_admin.txt"):
        p = auth.DIR / f
        if p.exists():
            p.unlink()
            print(f"\nremoved {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
