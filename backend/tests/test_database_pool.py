from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.database import (
    check_db_health,
    close_db_pool,
    get_db_connection,
    get_db_pool,
    init_db_pool,
)


@pytest.mark.asyncio
async def test_init_and_close_db_pool():
    """Test connection pool lifecycle."""
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool:
        mock_create_pool.return_value = mock_pool

        pool = await init_db_pool("postgresql://test:test@localhost:5432/test")
        assert pool is mock_pool
        assert get_db_pool() is mock_pool
        mock_create_pool.assert_called_once()

        await close_db_pool()
        mock_pool.close.assert_called_once()
        assert get_db_pool() is None


@pytest.mark.asyncio
async def test_get_db_connection_context_manager():
    """Test get_db_connection acquires and releases connection."""
    mock_conn = MagicMock()
    mock_pool = MagicMock()

    # async with pool.acquire() as conn:
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = mock_conn
    acquire_cm.__aexit__.return_value = None
    mock_pool.acquire.return_value = acquire_cm

    with patch("core.database._pool", mock_pool):
        async with get_db_connection() as conn:
            assert conn is mock_conn
        mock_pool.acquire.assert_called_once()


@pytest.mark.asyncio
async def test_check_db_health_success():
    """Test database healthcheck returns True on SELECT 1."""
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    mock_pool = MagicMock()
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = mock_conn
    acquire_cm.__aexit__.return_value = None
    mock_pool.acquire.return_value = acquire_cm

    with patch("core.database._pool", mock_pool):
        healthy = await check_db_health()
        assert healthy is True
        mock_conn.fetchval.assert_called_once_with("SELECT 1")


@pytest.mark.asyncio
async def test_check_db_health_failure():
    """Test database healthcheck returns False when pool fails."""
    with patch("core.database._pool", None):
        healthy = await check_db_health()
        assert healthy is False


# ---------------------------------------------------------------------------
# Privilege hygiene (SPEC-056 #8)
# ---------------------------------------------------------------------------

def test_the_pool_module_builds_no_supabase_clients():
    """`core/database.py` owns the asyncpg pool and nothing else.

    It used to also construct a second pair of PostgREST clients at import —
    duplicating `connector.py` — with `USER_SUPABASE_KEY or ADMIN_SUPABASE_KEY`.
    That is the silent service-role fallback SPEC-051 deliberately removed from
    `env.py`: omit the anon key and every "user" read quietly runs with
    privileges that bypass RLS. Two module-level sources of the same clients
    means the one nobody is looking at is the one that rots.
    """
    import core.database

    assert not hasattr(core.database, "admin_supabase")
    assert not hasattr(core.database, "user_supabase")


def test_the_anon_key_never_falls_back_to_the_service_role_key(monkeypatch):
    """Same rule, one layer down: an unset anon key must stay unset."""
    import importlib

    monkeypatch.setenv("ADMIN_SUPABASE_KEY", "service-role-key")
    monkeypatch.delenv("USER_SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    import core.config
    config = importlib.reload(core.config)
    try:
        assert config.USER_SUPABASE_KEY != "service-role-key"
        assert not config.USER_SUPABASE_KEY
    finally:
        # Restore the module for anything importing it later in the session.
        monkeypatch.undo()
        importlib.reload(core.config)
