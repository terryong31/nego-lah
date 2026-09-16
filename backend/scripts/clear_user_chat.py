"""
Ops script: clear one user's conversation history (the `messages` table).

Usage (from backend/, with env injected by Infisical — staging is the dev env):

    infisical run --env=dev  --path=/Backend -- uv run python scripts/clear_user_chat.py user@example.com           # dry run (default)
    infisical run --env=dev  --path=/Backend -- uv run python scripts/clear_user_chat.py user@example.com --apply   # delete
    # production: swap --env=dev for --env=prod — read the project URL it prints first.

Dry run is the default: it resolves the account, prints how many messages
would go, and touches nothing. `--apply` deletes every `messages` row for the
user. Both the buyer chat and the admin console's chat list are derived from
that one table, so this is the whole conversation history.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connector import admin_supabase  # noqa: E402


def find_user_by_email(email: str):
    """Paginate the auth admin API for a matching email (case-insensitive)."""
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


def _count_messages(user_id: str) -> int:
    resp = admin_supabase.table("messages").select("id", count="exact").eq("user_id", user_id).execute()
    return resp.count or 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply_changes = "--apply" in argv
    positional = [a for a in argv if not a.startswith("--")]
    if len(positional) != 1:
        print("Usage: uv run python scripts/clear_user_chat.py <email> [--apply]")
        return 2
    email = positional[0]

    print(f"Project: {os.environ.get('SUPABASE_URL') or '<SUPABASE_URL not set>'}")
    print(f"Mode: {'APPLY (deleting)' if apply_changes else 'DRY RUN (use --apply to delete)'}")

    user = find_user_by_email(email)
    if not user:
        print(f"No user found for {email} — nothing deleted.")
        return 1
    print(f"User: {user.email} -> id={user.id}")

    before = _count_messages(user.id)
    if not apply_changes:
        print(f"{before} message(s) belong to this user. Dry run — nothing deleted.")
        return 0

    admin_supabase.table("messages").delete().eq("user_id", user.id).execute()
    remaining = _count_messages(user.id)
    print(f"Deleted {before} message(s); {remaining} remain for this user.")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
