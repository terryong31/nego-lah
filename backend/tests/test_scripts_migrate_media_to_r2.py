"""Tests for scripts/migrate_media_to_r2.py (SPEC-108).

conftest pins SUPABASE_URL=https://test-project.supabase.co and
STORAGE_BUCKET=test-images, which is what makes LEGACY below "ours".
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import make_supabase_result
from scripts import migrate_media_to_r2 as migrate

LEGACY = "https://test-project.supabase.co/storage/v1/object/public/test-images"
GOOGLE = "https://lh3.googleusercontent.com/a/photo"


def _file(name, mimetype="image/jpeg"):
    return {"name": name, "id": f"id-{name}", "metadata": {"mimetype": mimetype}}


def _folder(name):
    return {"name": name, "id": None, "metadata": None}


@pytest.fixture
def admin(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(migrate, "admin_supabase", fake)
    return fake


def _bucket(admin, tree):
    bucket = admin.storage.from_.return_value
    bucket.list.side_effect = lambda prefix, options: tree.get(prefix, []) if options["offset"] == 0 else []
    bucket.download.side_effect = lambda key: f"bytes:{key}".encode()
    return bucket


# ---------------------------------------------------------------------------
# copy
# ---------------------------------------------------------------------------


def test_copy_walks_folders_and_copies_each_object_under_its_own_key(admin, fake_media):
    _bucket(
        admin,
        {
            "items": [_folder("item-1")],
            "items/item-1": [_file("0.jpeg"), _file("1.png", "image/png")],
            "avatars": [_file("u-1_ab12.png", "image/png")],
            "branding": [_file("logo.png", None)],
        },
    )

    tally = migrate.copy_objects(apply_changes=True)

    assert tally == {"copied": 4, "present": 0, "unmappable": 0, "failed": 0}
    assert [c.args for c in fake_media.put.call_args_list] == [
        ("items/item-1/0.jpeg", b"bytes:items/item-1/0.jpeg", "image/jpeg"),
        ("items/item-1/1.png", b"bytes:items/item-1/1.png", "image/png"),
        ("avatars/u-1_ab12.png", b"bytes:avatars/u-1_ab12.png", "image/png"),
        # No stored mimetype: guessed from the name.
        ("branding/logo.png", b"bytes:branding/logo.png", "image/png"),
    ]


def test_copy_is_a_dry_run_by_default(admin, fake_media):
    _bucket(admin, {"items": [_folder("i")], "items/i": [_file("0.jpeg")]})

    assert migrate.copy_objects()["copied"] == 1
    fake_media.put.assert_not_called()


def test_copy_skips_what_r2_already_has_so_a_rerun_is_free(admin, fake_media):
    _bucket(admin, {"items": [_folder("i")], "items/i": [_file("0.jpeg")]})
    fake_media.exists.return_value = True

    assert migrate.copy_objects(apply_changes=True) == {"copied": 0, "present": 1, "unmappable": 0, "failed": 0}
    fake_media.put.assert_not_called()


def test_copy_reports_a_key_the_cdn_cannot_serve_instead_of_mangling_it(admin, fake_media):
    _bucket(admin, {"avatars": [_file("my photo.png")]})

    assert migrate.copy_objects(apply_changes=True)["unmappable"] == 1
    fake_media.put.assert_not_called()


def test_copy_counts_a_failure_and_carries_on(admin, fake_media):
    _bucket(admin, {"items": [_folder("i")], "items/i": [_file("0.jpeg"), _file("1.jpeg")]})
    fake_media.put.side_effect = [Exception("R2 down"), "items/i/1.jpeg"]

    assert migrate.copy_objects(apply_changes=True) == {"copied": 1, "present": 0, "unmappable": 0, "failed": 1}


def test_list_pages_past_the_first_thousand(admin):
    bucket = admin.storage.from_.return_value
    first = [_file(f"{n}.jpeg") for n in range(migrate.LIST_PAGE)]
    bucket.list.side_effect = lambda prefix, options: first if options["offset"] == 0 else [_file("last.jpeg")]

    keys = [key for key, _ in migrate.iter_bucket_objects(bucket, "items/i")]

    assert len(keys) == migrate.LIST_PAGE + 1
    assert keys[-1] == "items/i/last.jpeg"


# ---------------------------------------------------------------------------
# rewrite
# ---------------------------------------------------------------------------


def _tables(admin, items=(), profiles=()):
    tables = {"items": MagicMock(), "user_profiles": MagicMock()}
    for name, rows in (("items", items), ("user_profiles", profiles)):
        query = tables[name].select.return_value.order.return_value.range.return_value
        query.execute.return_value = make_supabase_result(list(rows))
    admin.table.side_effect = lambda name: tables[name]
    return tables


def test_rewrite_turns_legacy_item_urls_into_keys(admin, fake_media):
    fake_media.exists.return_value = True
    image_path = {"0.jpeg": f"{LEGACY}/items/i-1/0.jpeg?", "a.png": "items/i-1/a.png", "x": GOOGLE}
    tables = _tables(admin, items=[{"id": "i-1", "image_path": json.dumps(image_path)}])
    admin.auth.admin.list_users.return_value = []

    tallies = migrate.rewrite_rows(apply_changes=True)

    assert tallies["items"] == {"rewritten": 1, "failed": 0}
    written = json.loads(tables["items"].update.call_args.args[0]["image_path"])
    assert written == {"0.jpeg": "items/i-1/0.jpeg", "a.png": "items/i-1/a.png", "x": GOOGLE}


def test_rewrite_leaves_a_url_alone_until_its_object_is_on_r2(admin, fake_media):
    fake_media.exists.return_value = False
    tables = _tables(
        admin,
        items=[{"id": "i-1", "image_path": json.dumps({"0.jpeg": f"{LEGACY}/items/i-1/0.jpeg"})}],
        profiles=[{"id": "u-1", "avatar_url": f"{LEGACY}/avatars/u-1_x.png"}],
    )
    admin.auth.admin.list_users.return_value = [
        SimpleNamespace(id="u-2", user_metadata={"custom_avatar_url": f"{LEGACY}/avatars/u-2/a.png"})
    ]

    tallies = migrate.rewrite_rows(apply_changes=True)

    assert all(t["rewritten"] == 0 for t in tallies.values())
    tables["items"].update.assert_not_called()
    admin.auth.admin.update_user_by_id.assert_not_called()


def test_rewrite_covers_profile_rows_and_auth_metadata(admin, fake_media):
    fake_media.exists.return_value = True
    tables = _tables(
        admin,
        profiles=[
            {"id": "u-1", "avatar_url": f"{LEGACY}/avatars/u-1_x.png"},
            {"id": "u-3", "avatar_url": "data:image/png;base64,AAAA"},
        ],
    )
    admin.auth.admin.list_users.return_value = [
        SimpleNamespace(id="u-2", user_metadata={"custom_avatar_url": f"{LEGACY}/avatars/u-2/a.png", "k": "v"}),
        SimpleNamespace(id="u-4", user_metadata={"avatar_url": GOOGLE}),
    ]

    tallies = migrate.rewrite_rows(apply_changes=True)

    assert tallies["user_profiles"]["rewritten"] == 1
    assert tables["user_profiles"].update.call_args.args[0] == {"avatar_url": "avatars/u-1_x.png"}
    assert tallies["auth"]["rewritten"] == 1
    admin.auth.admin.update_user_by_id.assert_called_once_with(
        "u-2", {"user_metadata": {"custom_avatar_url": "avatars/u-2/a.png", "k": "v"}}
    )


def test_rewrite_is_a_dry_run_by_default(admin, fake_media):
    fake_media.exists.return_value = True
    tables = _tables(admin, items=[{"id": "i-1", "image_path": json.dumps({"0": f"{LEGACY}/items/i-1/0.jpeg"})}])
    admin.auth.admin.list_users.return_value = []

    assert migrate.rewrite_rows()["items"]["rewritten"] == 1
    tables["items"].update.assert_not_called()


def test_rewrite_counts_failures(admin, fake_media):
    fake_media.exists.return_value = True
    tables = _tables(
        admin,
        items=[{"id": "i-1", "image_path": json.dumps({"0": f"{LEGACY}/items/i-1/0.jpeg"})}],
        profiles=[{"id": "u-1", "avatar_url": f"{LEGACY}/avatars/u-1_x.png"}],
    )
    tables["items"].update.side_effect = Exception("db down")
    tables["user_profiles"].update.side_effect = Exception("db down")
    admin.auth.admin.list_users.return_value = [
        SimpleNamespace(id="u-2", user_metadata={"custom_avatar_url": f"{LEGACY}/avatars/u-2/a.png"})
    ]
    admin.auth.admin.update_user_by_id.side_effect = Exception("auth down")

    tallies = migrate.rewrite_rows(apply_changes=True)

    assert {name: t["failed"] for name, t in tallies.items()} == {"items": 1, "user_profiles": 1, "auth": 1}


def test_rewrite_skips_unreadable_and_non_map_image_paths(admin, fake_media):
    fake_media.exists.return_value = True
    _tables(admin, items=[{"id": "a", "image_path": "not-json"}, {"id": "b", "image_path": json.dumps(["x"])}])
    admin.auth.admin.list_users.return_value = []

    assert migrate.rewrite_rows(apply_changes=True)["items"] == {"rewritten": 0, "failed": 0}


def test_iter_users_pages_until_a_short_page(admin):
    full = [SimpleNamespace(id=f"u{n}") for n in range(migrate.USER_PAGE)]
    admin.auth.admin.list_users.side_effect = [SimpleNamespace(users=full), SimpleNamespace(users=[])]

    assert len(list(migrate.iter_users())) == migrate.USER_PAGE


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_needs_a_step(capsys):
    assert migrate.main([]) == 2
    assert "copy" in capsys.readouterr().out


def test_main_runs_each_step_and_fails_on_a_failure(monkeypatch):
    monkeypatch.setattr(migrate, "copy_objects", lambda apply: {"failed": 0, "apply": apply})
    monkeypatch.setattr(migrate, "rewrite_rows", lambda apply: {"items": {"failed": 1}})

    assert migrate.main(["copy", "--apply"]) == 0
    assert migrate.main(["rewrite"]) == 1
