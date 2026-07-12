"""
Grant or revoke admin access for an existing Supabase user.

Admin access = app_metadata.role == "admin" (authoritative, set via the service
role) PLUS a Redis allowlist entry (fast, instantly revocable). This script keeps
both in sync.

The user must already have a normal Supabase account (email + password). Self
sign-up does NOT grant admin — only this script does.

Usage (run from the backend/ directory, with backend/.env populated):

    python -m scripts.promote_admin grant   user@example.com
    python -m scripts.promote_admin revoke  user@example.com

"""
import sys

# Allow running both as `python -m scripts.promote_admin` and `python scripts/promote_admin.py`
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

from admin_session import grant_admin, revoke_admin
from connector import admin_supabase


def _find_user(email: str):
    email = email.strip().lower()
    # list_users paginates; scan for the matching email.
    page = 1
    while True:
        resp = admin_supabase.auth.admin.list_users(page=page, per_page=200)
        # Newer SDKs may wrap the page in an envelope object instead of returning
        # a bare list; accept both so pagination doesn't silently break.
        users = resp if isinstance(resp, list) else getattr(resp, "users", resp)
        if not users:
            return None
        for u in users:
            if (u.email or "").lower() == email:
                return u
        if len(users) < 200:
            return None
        page += 1


def grant(email: str):
    user = _find_user(email)
    if not user:
        print(f"❌ No Supabase user found for {email}. Create the account first.")
        sys.exit(1)
    meta = dict(user.app_metadata or {})
    meta["role"] = "admin"
    admin_supabase.auth.admin.update_user_by_id(user.id, {"app_metadata": meta})
    grant_admin(user.id, email)
    print(f"✅ Granted admin to {email} ({user.id}).")
    print("   They must now log in via the /_console admin login (password + email OTP).")


def revoke(email: str):
    user = _find_user(email)
    if not user:
        print(f"❌ No Supabase user found for {email}.")
        sys.exit(1)
    meta = dict(user.app_metadata or {})
    meta.pop("role", None)
    admin_supabase.auth.admin.update_user_by_id(user.id, {"app_metadata": meta})
    revoke_admin(user.id)
    print(f"✅ Revoked admin from {email} ({user.id}). Any active session will fail on its next request.")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("grant", "revoke"):
        print(__doc__)
        sys.exit(2)
    action, email = sys.argv[1], sys.argv[2]
    (grant if action == "grant" else revoke)(email)


if __name__ == "__main__":
    main()
