from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from supabase import Client, create_client

from core.config import ADMIN_SUPABASE_KEY, DATABASE_URL, SUPABASE_URL, USER_SUPABASE_KEY
from core.telemetry import logger

# --- Supabase REST Data API & Auth Clients (Legacy / Auth compatibility) ---
if not SUPABASE_URL or not (ADMIN_SUPABASE_KEY or USER_SUPABASE_KEY):
    raise ValueError("Missing Supabase configuration. Ensure SUPABASE_URL and ADMIN_SUPABASE_KEY are set.")

_admin_key = ADMIN_SUPABASE_KEY or USER_SUPABASE_KEY
_user_key = USER_SUPABASE_KEY or ADMIN_SUPABASE_KEY

admin_supabase: Client = create_client(SUPABASE_URL, _admin_key)
user_supabase: Client = create_client(SUPABASE_URL, _user_key)


# --- PostgreSQL Connection Pool (Direct Supabase Pooler) ---
_pool: asyncpg.Pool | None = None


async def init_db_pool(
    dsn: str | None = None,
    min_size: int = 1,
    max_size: int = 10,
    timeout: float = 10.0
) -> asyncpg.Pool | None:
    """
    Initialize an asynchronous PostgreSQL connection pool targeting Supabase.
    Uses DATABASE_URL (Supavisor / PgBouncer pooler).
    """
    global _pool
    connection_string = dsn or DATABASE_URL
    if not connection_string:
        logger.warning("DATABASE_URL unset. PostgreSQL connection pool disabled.")
        return None

    try:
        # Strip unsupported query params if present for asyncpg
        clean_dsn = connection_string.split("?")[0] if "?" in connection_string else connection_string
        _pool = await asyncpg.create_pool(
            dsn=clean_dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=timeout,
        )
        logger.info("🐘 PostgreSQL connection pool established")
        return _pool
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL connection pool: {e}")
        return None


async def close_db_pool() -> None:
    """Close the active connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


def get_db_pool() -> asyncpg.Pool | None:
    """Get the active asyncpg connection pool instance."""
    return _pool


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Context manager to acquire a connection from the pool.
    Usage:
        async with get_db_connection() as conn:
            rows = await conn.fetch("SELECT * FROM items WHERE status = $1", "active")
    """
    if _pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    async with _pool.acquire() as connection:
        yield connection


async def check_db_health() -> bool:
    """Run a fast probe (SELECT 1) against the connection pool."""
    if _pool is None:
        return False
    try:
        async with get_db_connection() as conn:
            val = await conn.fetchval("SELECT 1")
            return val == 1
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False
