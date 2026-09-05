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
