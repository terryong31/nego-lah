"""
One-off migration (SPEC-029): move self-uploaded avatars to `custom_avatar_url`.

Supabase re-syncs `user_metadata` from the identity provider's claims on every
OAuth sign-in, and Google's claims carry `avatar_url`. Uploads used to be written
to that same key, so a Google login silently replaced them with the Google photo.
Uploads now go to `custom_avatar_url`, which no provider writes.

This copies the still-intact uploads across — users who have not signed in with
Google since uploading. Anyone whose `avatar_url` was already overwritten has
lost the reference and has to re-upload; nothing can recover that here.

A self-upload is told apart from a provider photo by its URL: ours are served
from this project's own storage bucket under `avatars/`.

Safe to re-run: users already carrying a `custom_avatar_url` are skipped.

Usage:
    uv run python scripts/backfill_custom_avatar.py            # dry run (default)
    uv run python scripts/backfill_custom_avatar.py --apply    # write the changes

Uses the service-role client, so run it from the backend with env configured:
    infisical run --env=prod --path=/Backend -- uv run python scripts/backfill_custom_avatar.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connector import admin_supabase  # noqa: E402
from env import STORAGE_BUCKET, SUPABASE_URL  # noqa: E402

PAGE_SIZE = 200


def self_hosted_avatar_prefix() -> str:
    """The public-URL prefix that `PUT /user/{id}/profile` uploads land under."""
    base = (SUPABASE_URL or "").rstrip("/")
    bucket = STORAGE_BUCKET or "images"
    return f"{base}/storage/v1/object/public/{bucket}/avatars/"


def is_self_hosted_avatar(url: object) -> bool:
    """True only for an avatar we uploaded ourselves, never a provider photo.

    Matching on the full prefix (host + bucket + folder) rather than a substring
    keeps another Supabase project, or an item image in the same bucket, from
    being mistaken for one of ours.
    """
    if not isinstance(url, str) or not url:
        return False
    return url.startswith(self_hosted_avatar_prefix())


def iter_users():
    """Yield every auth user, one page at a time."""
    page = 1
    while True:
        resp = admin_supabase.auth.admin.list_users(page=page, per_page=PAGE_SIZE)
        users = resp if isinstance(resp, list) else getattr(resp, "users", resp)
        if not users:
            return
        yield from users
        if len(users) < PAGE_SIZE:
            return
        page += 1


def backfill(apply_changes: bool = False) -> dict:
    """Copy self-uploaded avatars to `custom_avatar_url`. Returns a tally."""
    scanned = migrated = skipped = failed = 0

    for user in iter_users():
        scanned += 1
        metadata = dict(getattr(user, "user_metadata", None) or {})

        if metadata.get("custom_avatar_url"):
            skipped += 1
            continue

        avatar_url = metadata.get("avatar_url")
        if not is_self_hosted_avatar(avatar_url):
            skipped += 1
            continue

        print(f"  {user.id} ({user.email}) -> {avatar_url}")

        if not apply_changes:
            migrated += 1
            continue

        # `avatar_url` is deliberately left in place: it is the provider's key to
        # own, and the clients already prefer `custom_avatar_url` over it.
        metadata["custom_avatar_url"] = avatar_url
        try:
            admin_supabase.auth.admin.update_user_by_id(
                user.id, {"user_metadata": metadata}
            )
            migrated += 1
        except Exception as e:
            print(f"  !! failed for {user.id}: {e}")
            failed += 1

    return {
        "scanned": scanned,
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply_changes = "--apply" in argv

    print(f"Matching uploads under: {self_hosted_avatar_prefix()}")
    print("Mode: APPLY (writing changes)" if apply_changes else "Mode: DRY RUN (use --apply to write)")

    result = backfill(apply_changes=apply_changes)

    verb = "migrated" if apply_changes else "would migrate"
    print(
        f"\nScanned {result['scanned']} users: {verb} {result['migrated']}, "
        f"skipped {result['skipped']}, failed {result['failed']}."
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
