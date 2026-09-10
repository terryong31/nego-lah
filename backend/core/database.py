from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg

from core.config import DATABASE_URL
from core.telemetry import logger

# This module owns the asyncpg pool and nothing else (SPEC-056 #8).
#
# It also used to construct a second pair of PostgREST clients here, duplicating
# `connector.py`, keyed `USER_SUPABASE_KEY or ADMIN_SUPABASE_KEY`. That fallback
# is the one SPEC-051 deleted from `env.py`: with the anon key unset, every
# "user" client silently becomes a service-role client and RLS stops applying.
# Nothing imported these — which is exactly why nobody noticed. `connector.py`
# is the single source of Supabase clients; go there.


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
