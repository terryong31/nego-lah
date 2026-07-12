"""
Tests for connector.py — the module that builds the two module-level Supabase
singletons (`user_supabase`, `admin_supabase`) and the `_MissingSupabaseClient`
fallback used when Supabase isn't configured / fails to construct.

IMPORTANT — module-level singleton safety:
connector.py builds `user_supabase` / `admin_supabase` once, at import time, by
calling `_create_supabase_client(...)`. To exercise the missing-env and
exception-fallback branches of the *module-level* assignment (not just the
helper function in isolation) we have to `importlib.reload(connector)` after
changing what it sees. Every test that reloads connector restores it (via a
`finally` block, calling `monkeypatch.undo()` *before* reloading again so the
restore reload runs against the real test env / real `create_client`) before
the test function returns, so later test files in a full-suite run always see
a working `connector` module. An autouse fixture below double-checks this as
a defense-in-depth safety net.

We never touch `os.environ` or reload `env.py` here: backend/.env exists on
disk with real credentials, and `env.py`'s `load_dotenv(..., override=False)`
would happily fill in any var we deleted from `os.environ` with the real
value. Instead we monkeypatch the already-imported `env` module's attributes
(`env.SUPABASE_URL` etc.) directly — connector's `from env import X` re-reads
those attributes on every reload without ever re-executing env.py.
"""

import importlib
from unittest.mock import MagicMock

import pytest

import connector


@pytest.fixture(autouse=True)
def _ensure_connector_restored():
    """Defense in depth: if a test somehow left connector in the broken
    (missing-env / fallback) state, put it back before the next test runs."""
    yield
    if isinstance(connector.admin_supabase, connector._MissingSupabaseClient) or isinstance(
        connector.user_supabase, connector._MissingSupabaseClient
    ):
        importlib.reload(connector)


# =====================================================================
# _MissingSupabaseClient
# =====================================================================


def test_missing_client_table_raises_runtime_error_listing_missing_vars():
    client = connector._MissingSupabaseClient(["SUPABASE_URL", "USER_SUPABASE_KEY"])
    with pytest.raises(RuntimeError) as exc_info:
        client.table("items")
    message = str(exc_info.value)
    assert "Supabase is not configured" in message
    assert "SUPABASE_URL" in message
    assert "USER_SUPABASE_KEY" in message


def test_missing_client_table_raises_regardless_of_args_kwargs():
    client = connector._MissingSupabaseClient(["ADMIN_SUPABASE_KEY"])
    with pytest.raises(RuntimeError, match="ADMIN_SUPABASE_KEY"):
        client.table("items", schema="public")


def test_missing_client_stores_missing_env_list():
    client = connector._MissingSupabaseClient(["SUPABASE_URL"])
    assert client.missing_env == ["SUPABASE_URL"]


# =====================================================================
# _create_supabase_client — direct unit tests (no reload needed: the
# function reads connector's module-global SUPABASE_URL/create_client names
# on every call, so monkeypatching those names on the connector module is
# enough).
# =====================================================================


def test_create_client_success_calls_create_client_with_expected_kwargs(monkeypatch):
    sentinel = object()
    mock_create = MagicMock(return_value=sentinel)
    monkeypatch.setattr(connector, "create_client", mock_create)

    result = connector._create_supabase_client("some-anon-key", "USER_SUPABASE_KEY")

    assert result is sentinel
    mock_create.assert_called_once_with(supabase_url=connector.SUPABASE_URL, supabase_key="some-anon-key")


def test_create_client_missing_url_only(monkeypatch):
    monkeypatch.setattr(connector, "SUPABASE_URL", "")
    result = connector._create_supabase_client("a-real-key", "USER_SUPABASE_KEY")
    assert isinstance(result, connector._MissingSupabaseClient)
    assert result.missing_env == ["SUPABASE_URL"]


def test_create_client_missing_key_only():
    # connector.SUPABASE_URL is untouched here, so it's whatever the real test
    # env provided (truthy per conftest's _TEST_ENV) -- only the key is missing.
    assert connector.SUPABASE_URL
    result = connector._create_supabase_client("", "USER_SUPABASE_KEY")
    assert isinstance(result, connector._MissingSupabaseClient)
    assert result.missing_env == ["USER_SUPABASE_KEY"]


def test_create_client_missing_url_and_key(monkeypatch):
    monkeypatch.setattr(connector, "SUPABASE_URL", None)
    result = connector._create_supabase_client(None, "ADMIN_SUPABASE_KEY")
    assert isinstance(result, connector._MissingSupabaseClient)
    assert result.missing_env == ["SUPABASE_URL", "ADMIN_SUPABASE_KEY"]


def test_create_client_exception_falls_back_to_missing_client(monkeypatch):
    monkeypatch.setattr(connector, "create_client", MagicMock(side_effect=RuntimeError("network down")))
    result = connector._create_supabase_client("a-real-key", "ADMIN_SUPABASE_KEY")
    assert isinstance(result, connector._MissingSupabaseClient)
    # Per the fallback code, the exception path always reports both names,
    # even though only create_client (not the missing-var precheck) failed.
    assert result.missing_env == ["SUPABASE_URL", "ADMIN_SUPABASE_KEY"]
    with pytest.raises(RuntimeError, match="ADMIN_SUPABASE_KEY"):
        result.table("items")


# =====================================================================
# Module-level singletons via importlib.reload — exercises the real
# top-level `user_supabase = _create_supabase_client(...)` /
# `admin_supabase = _create_supabase_client(...)` lines under each scenario.
# =====================================================================


def test_reload_with_real_env_builds_working_clients():
    """Baseline: reloading with the normal conftest env produces real clients,
    not the missing-env fallback, for both singletons."""
    importlib.reload(connector)
    assert not isinstance(connector.user_supabase, connector._MissingSupabaseClient)
    assert not isinstance(connector.admin_supabase, connector._MissingSupabaseClient)


def test_reload_success_path_uses_create_client(monkeypatch):
    sentinel_user = object()
    sentinel_admin = object()
    mock_create = MagicMock(side_effect=[sentinel_user, sentinel_admin])
    try:
        monkeypatch.setattr("supabase.create_client", mock_create)
        importlib.reload(connector)
        # connector.py builds user_supabase first, then admin_supabase.
        assert connector.user_supabase is sentinel_user
        assert connector.admin_supabase is sentinel_admin
        assert mock_create.call_count == 2
    finally:
        monkeypatch.undo()
        importlib.reload(connector)


def test_reload_missing_env_produces_missing_clients_for_both_singletons(monkeypatch):
    try:
        monkeypatch.setattr("env.SUPABASE_URL", "")
        monkeypatch.setattr("env.USER_SUPABASE_KEY", "")
        monkeypatch.setattr("env.ADMIN_SUPABASE_KEY", "")
        importlib.reload(connector)

        assert isinstance(connector.user_supabase, connector._MissingSupabaseClient)
        assert connector.user_supabase.missing_env == ["SUPABASE_URL", "USER_SUPABASE_KEY"]
        assert isinstance(connector.admin_supabase, connector._MissingSupabaseClient)
        assert connector.admin_supabase.missing_env == ["SUPABASE_URL", "ADMIN_SUPABASE_KEY"]

        with pytest.raises(RuntimeError, match="USER_SUPABASE_KEY"):
            connector.user_supabase.table("items")
        with pytest.raises(RuntimeError, match="ADMIN_SUPABASE_KEY"):
            connector.admin_supabase.table("items")
    finally:
        # Undo the env-attribute patches *before* reloading, so the restoring
        # reload runs against the real test env (not the broken one above).
        monkeypatch.undo()
        importlib.reload(connector)


def test_reload_missing_only_admin_key_leaves_user_client_working(monkeypatch):
    try:
        monkeypatch.setattr("env.ADMIN_SUPABASE_KEY", "")
        importlib.reload(connector)

        assert not isinstance(connector.user_supabase, connector._MissingSupabaseClient)
        assert isinstance(connector.admin_supabase, connector._MissingSupabaseClient)
        assert connector.admin_supabase.missing_env == ["ADMIN_SUPABASE_KEY"]
    finally:
        monkeypatch.undo()
        importlib.reload(connector)


def test_reload_create_client_exception_falls_back_for_both_singletons(monkeypatch):
    try:
        monkeypatch.setattr("supabase.create_client", MagicMock(side_effect=Exception("boom")))
        importlib.reload(connector)

        assert isinstance(connector.user_supabase, connector._MissingSupabaseClient)
        assert connector.user_supabase.missing_env == ["SUPABASE_URL", "USER_SUPABASE_KEY"]
        assert isinstance(connector.admin_supabase, connector._MissingSupabaseClient)
        assert connector.admin_supabase.missing_env == ["SUPABASE_URL", "ADMIN_SUPABASE_KEY"]
    finally:
        monkeypatch.undo()
        importlib.reload(connector)
