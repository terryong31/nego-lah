"""
Create (or update) a Supabase user and flag it as an admin in one step.

This is the bootstrap for the admin console. It:
  1. Creates the auth user with email + password (email auto-confirmed so they can
     sign in immediately), or updates the password if the user already exists.
  2. Sets app_metadata.role == "admin" (authoritative, service-role only).
  3. Adds the user to the Redis admin allowlist (best-effort; login self-heals it).

Run from the backend/ directory with backend/.env populated:

    python -m scripts.create_admin you@example.com 'your-password'

Login afterwards uses 2FA: password (this one) + a 6-digit email OTP. For the OTP
to be a code (not a magic link), the Supabase Magic Link email template must
include {{ .Token }}.
"""
import os
import sys

# Allow `python scripts/create_admin.py ...` as well as `-m scripts.create_admin`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connector import admin_supabase
from admin_session import grant_admin


def _find_user(email: str):
    email = email.strip().lower()
    page = 1
    while True:
        users = admin_supabase.auth.admin.list_users(page=page, per_page=200)
        if not users:
            return None
        for u in users:
            if (u.email or "").lower() == email:
                return u
        if len(users) < 200:
            return None
        page += 1


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    email = sys.argv[1].strip().lower()
    password = sys.argv[2]

    existing = _find_user(email)
    if existing:
        admin_supabase.auth.admin.update_user_by_id(existing.id, {
            "password": password,
            "email_confirm": True,
            "app_metadata": {**(existing.app_metadata or {}), "role": "admin"},
        })
        user_id = existing.id
        print(f"♻️  Updated existing user {email} ({user_id}) and set role=admin.")
    else:
        created = admin_supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "app_metadata": {"role": "admin"},
        })
        user_id = created.user.id
        print(f"✅ Created user {email} ({user_id}) with role=admin.")

    grant_admin(user_id, email)
    print("✅ Admin allowlist updated (Redis).")
    print("\nLog in at /_console/login — password, then the 6-digit code emailed to you.")


if __name__ == "__main__":
    main()
