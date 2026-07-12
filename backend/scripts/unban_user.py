"""
Recovery script: lift a ban on a user (Supabase auth + app DB flag + cache).

Usage:
    .venv/bin/python scripts/unban_user.py user@example.com

Uses the service-role client, so run it from the backend with env configured.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connector import admin_supabase  # noqa: E402


def find_user_by_email(email: str):
    # Paginate through users to find the matching email.
    page = 1
    while True:
        resp = admin_supabase.auth.admin.list_users(page=page, per_page=200)
        users = resp if isinstance(resp, list) else getattr(resp, "users", resp)
        if not users:
            return None
        for u in users:
            if (u.email or "").lower() == email.lower():
                return u
        if len(users) < 200:
            return None
        page += 1


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)

    email = sys.argv[1]
    user = find_user_by_email(email)
    if not user:
        print(f"No user found for {email}")
        return

    print(f"Found user {email} -> id={user.id}")

    # 1. Lift the Supabase auth-level ban (allows login again).
    admin_supabase.auth.admin.update_user_by_id(user.id, {"ban_duration": "none"})
    print("  - Supabase auth ban lifted (ban_duration=none)")

    # 2. Clear the app-side DB flag.
    admin_supabase.table("user_profiles").upsert(
        {"id": user.id, "is_banned": False, "updated_at": "now()"}
    ).execute()
    print("  - user_profiles.is_banned = False")

    # 3. Drop the cached ban status.
    try:
        from cache import invalidate_ban_status
        invalidate_ban_status(user.id)
        print("  - cache invalidated")
    except Exception as e:
        print(f"  - cache invalidate skipped: {e}")

    print("Done. You can log in again.")


if __name__ == "__main__":
    main()
