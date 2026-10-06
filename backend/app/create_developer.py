"""Create (or reset) a developer login with access to every part of the app.

    python -m app.create_developer --email dev@example.com
    python -m app.create_developer --email dev@example.com --reset-password

Uses Supabase's admin API, so it needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
in backend/.env (keep the service-role key out of the frontend and out of git).
A random password is printed once; nothing is stored in code or files.
"""
import argparse
import os
import secrets

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

from app.database.session import engine

load_dotenv()


def admin_client() -> httpx.Client:
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env first.")
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go in Authorization; the newer
    # "sb_secret_..." keys are not JWTs and are sent only as apikey.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return httpx.Client(base_url=f"{url}/auth/v1/admin", timeout=30, headers=headers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--reset-password", action="store_true", help="Give an existing user a new password")
    args = parser.parse_args()
    email = args.email.strip().lower()
    password = secrets.token_urlsafe(18)
    with engine.connect() as connection:
        user_id = connection.execute(text("SELECT id::text FROM auth.users WHERE lower(email) = :email"),
                                     {"email": email}).scalar()
    with admin_client() as client:
        if user_id is None:
            response = client.post("/users", json={"email": email, "password": password, "email_confirm": True,
                                                   "app_metadata": {"role": "developer"}})
            response.raise_for_status()
            user_id = response.json()["id"]
        elif args.reset_password:
            client.put(f"/users/{user_id}", json={"password": password}).raise_for_status()
        else:
            password = None
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO user_accounts (user_id, email, role, plan, plan_status)
            VALUES (:user_id, :email, 'developer', 'pro', 'active')
            ON CONFLICT (user_id) DO UPDATE SET role='developer', plan='pro', plan_status='active', updated_at=NOW()
        """), {"user_id": user_id, "email": email})
    print(f"Developer access granted to {email}.")
    if password:
        print(f"Password (shown once): {password}")
    else:
        print("The existing password is unchanged; add --reset-password to set a new one.")


if __name__ == "__main__":
    main()
