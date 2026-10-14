#!/usr/bin/env python3
"""After resetting the Supabase database password in the dashboard, put the new one
everywhere this project uses it. Run from the repo root in your own terminal:

    .venv/bin/python scripts/rotate_database_password.py

It asks for the password without echoing it, checks it connects, updates
backend/.env (DATABASE_URL) and the GitHub Actions secret DATABASE_URL, and copies
the new connection string to the clipboard for Railway. Nothing secret is printed.
"""
import getpass
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

REPO = "zaina-saif/distressed-properties"
ENV = Path(__file__).resolve().parents[1] / "backend" / ".env"


def with_password(url: str, password: str) -> str:
    parts = urlsplit(url)
    user = parts.username or "postgres"
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, f"{user}:{quote(password, safe='')}@{host}", parts.path, parts.query, parts.fragment))


def main() -> int:
    text = ENV.read_text()
    match = re.search(r"^DATABASE_URL\s*=\s*(\S+)\s*$", text, re.M)
    if not match:
        print(f"DATABASE_URL not found in {ENV}")
        return 1
    password = getpass.getpass("New Supabase database password (hidden): ")
    if not password or password != getpass.getpass("Again: "):
        print("The two entries differ (or are empty); nothing changed.")
        return 1
    url = with_password(match.group(1), password)

    print("1/4 checking the new password connects...")
    try:
        import psycopg2
        psycopg2.connect(url, connect_timeout=15).close()
    except Exception as exc:  # noqa: BLE001
        print(f"    could not connect ({type(exc).__name__}); nothing changed. Was the reset saved?")
        return 1

    print("2/4 updating backend/.env ...")
    temp = ENV.with_suffix(".tmp")
    temp.write_text(text[:match.start(1)] + url + text[match.end(1):])
    os.chmod(temp, 0o600)
    temp.replace(ENV)

    print("3/4 updating the GitHub Actions secret DATABASE_URL ...")
    result = subprocess.run(["gh", "secret", "set", "DATABASE_URL", "-R", REPO], input=url, text=True,
                            capture_output=True)
    print("    done" if result.returncode == 0 else f"    FAILED: {result.stderr.strip()[:200]}")

    print("4/4 copying the new DATABASE_URL to the clipboard for Railway ...")
    subprocess.run(["pbcopy"], input=url, text=True, check=False)
    print("    In Railway: the API service (the one serving api.sheriffsalehunter.ai) > Variables >")
    print("    DATABASE_URL > paste > Deploy.")
    print("    Afterwards copy something else so the URL does not stay on the clipboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
