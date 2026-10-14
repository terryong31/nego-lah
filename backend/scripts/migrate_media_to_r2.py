"""
One-off migration (SPEC-108): user media moves from Supabase Storage to R2.

Two steps, in this order, each a dry run unless `--apply` is given:

  copy     Copy every object under items/, avatars/ and branding/ from the
           Supabase bucket to R2 under the same key. Objects already on R2 are
           skipped, so it is safe to re-run.
  rewrite  Rewrite stored Supabase URLs to keys: `items.image_path`,
           `user_profiles.avatar_url` and auth `custom_avatar_url`. A value is
           only rewritten when its object is already on R2.

The deployed backend reads legacy URLs as keys, so `rewrite` changes nothing a
visitor sees — it removes the vendor URL from the data. `copy` has to finish
before the SPEC-108 backend is deployed, or legacy photos 404 on the CDN.

A key the CDN cannot serve (an early upload whose name kept a space from the
original filename) is reported as unmappable and left on Supabase.

Usage:
    infisical run --env=prod --path=/Backend -- uv run python scripts/migrate_media_to_r2.py copy
    infisical run --env=prod --path=/Backend -- uv run python scripts/migrate_media_to_r2.py copy --apply
    infisical run --env=prod --path=/Backend -- uv run python scripts/migrate_media_to_r2.py rewrite --apply
"""

import json
import mimetypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.connector import admin_supabase  # noqa: E402
from core.env import STORAGE_BUCKET  # noqa: E402
from core.media import media_key, media_store  # noqa: E402
from core.pagination import fetch_all  # noqa: E402

PREFIXES = ("items", "avatars", "branding")
LIST_PAGE = 1000
USER_PAGE = 200


# ---------------------------------------------------------------------------
# copy
# ---------------------------------------------------------------------------


def iter_bucket_objects(bucket, prefix: str):
    """Yield (key, content_type) for every object under `prefix`, recursively.

    Supabase lists one folder level at a time; a folder comes back with no `id`.
    """
    offset = 0
    while True:
        entries = bucket.list(prefix, {"limit": LIST_PAGE, "offset": offset}) or []
        for entry in entries:
            path = f"{prefix}/{entry['name']}"
            if entry.get("id") is None:
                yield from iter_bucket_objects(bucket, path)
            else:
                content_type = (entry.get("metadata") or {}).get("mimetype")
                yield path, content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if len(entries) < LIST_PAGE:
            return
        offset += LIST_PAGE


def copy_objects(apply_changes: bool = False) -> dict:
    bucket = admin_supabase.storage.from_(STORAGE_BUCKET)
    tally = {"copied": 0, "present": 0, "unmappable": 0, "failed": 0}

    for prefix in PREFIXES:
        for key, content_type in iter_bucket_objects(bucket, prefix):
            if media_key(key) != key:
                print(f"  ?? unmappable key, left on Supabase: {key!r}")
                tally["unmappable"] += 1
                continue
            try:
                if media_store.exists(key):
                    tally["present"] += 1
                    continue
                print(f"  {key} ({content_type})")
                if apply_changes:
                    media_store.put(key, bucket.download(key), content_type)
                tally["copied"] += 1
            except Exception as e:
                print(f"  !! {key}: {e}")
                tally["failed"] += 1
    return tally


# ---------------------------------------------------------------------------
# rewrite
# ---------------------------------------------------------------------------


def _as_key(value):
    """The key to store in place of `value`, or None to leave it alone."""
    key = media_key(value)
    if key is None or key == value or not media_store.exists(key):
        return None
    return key


def rewrite_items(apply_changes: bool) -> dict:
    tally = {"rewritten": 0, "failed": 0}
    rows = fetch_all(lambda: admin_supabase.table("items").select("id, image_path").order("id"))
    for row in rows:
        try:
            current = json.loads(row.get("image_path") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(current, dict):
            continue
        updated = {name: _as_key(value) or value for name, value in current.items()}
        if updated == current:
            continue
        print(f"  items/{row['id']}: {len(current)} photo(s)")
        tally["rewritten"] += 1
        if apply_changes:
            try:
                admin_supabase.table("items").update({"image_path": json.dumps(updated)}).eq("id", row["id"]).execute()
            except Exception as e:
                print(f"  !! items/{row['id']}: {e}")
                tally["failed"] += 1
    return tally


def rewrite_profiles(apply_changes: bool) -> dict:
    tally = {"rewritten": 0, "failed": 0}
    rows = fetch_all(lambda: admin_supabase.table("user_profiles").select("id, avatar_url").order("id"))
    for row in rows:
        key = _as_key(row.get("avatar_url"))
        if not key:
            continue
        print(f"  user_profiles/{row['id']} -> {key}")
        tally["rewritten"] += 1
        if apply_changes:
            try:
                admin_supabase.table("user_profiles").update({"avatar_url": key}).eq("id", row["id"]).execute()
            except Exception as e:
                print(f"  !! user_profiles/{row['id']}: {e}")
                tally["failed"] += 1
    return tally


def iter_users():
    page = 1
    while True:
        resp = admin_supabase.auth.admin.list_users(page=page, per_page=USER_PAGE)
        users = resp if isinstance(resp, list) else getattr(resp, "users", resp)
        if not users:
            return
        yield from users
        if len(users) < USER_PAGE:
            return
        page += 1


def rewrite_auth_avatars(apply_changes: bool) -> dict:
    tally = {"rewritten": 0, "failed": 0}
    for user in iter_users():
        metadata = dict(getattr(user, "user_metadata", None) or {})
        key = _as_key(metadata.get("custom_avatar_url"))
        if not key:
            continue
        print(f"  auth/{user.id} -> {key}")
        tally["rewritten"] += 1
        if apply_changes:
            metadata["custom_avatar_url"] = key
            try:
                admin_supabase.auth.admin.update_user_by_id(user.id, {"user_metadata": metadata})
            except Exception as e:
                print(f"  !! auth/{user.id}: {e}")
                tally["failed"] += 1
    return tally


def rewrite_rows(apply_changes: bool = False) -> dict:
    return {
        "items": rewrite_items(apply_changes),
        "user_profiles": rewrite_profiles(apply_changes),
        "auth": rewrite_auth_avatars(apply_changes),
    }


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    step = next((arg for arg in argv if not arg.startswith("-")), None)
    apply_changes = "--apply" in argv
    if step not in ("copy", "rewrite"):
        print(__doc__)
        return 2

    print("Mode: APPLY (writing changes)" if apply_changes else "Mode: DRY RUN (use --apply to write)")
    if step == "copy":
        tally = copy_objects(apply_changes)
        print(f"\n{tally}")
        return 1 if tally["failed"] else 0

    tallies = rewrite_rows(apply_changes)
    print(f"\n{tallies}")
    return 1 if any(t["failed"] for t in tallies.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
