"""
Tests for auth_middleware.py:
- verify_user_token: header parsing, cache hit/miss, Supabase validation,
  exception handling, ban enforcement.
- get_user_id_from_body_or_token: body/token user_id consistency check.
"""
import asyncio
import contextlib
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from auth_middleware import get_user_id_from_body_or_token, verify_user_token
from cache import cache_ban_status, cache_token_user, get_cached_user_by_token
from conftest import make_supabase_result


def make_request(headers: dict):
    """Minimal stand-in for fastapi.Request -- verify_user_token only touches
    `request.headers.get(...)`, and a plain dict supports that."""
    return SimpleNamespace(headers=headers)


def configure_ban_check(fake_supabase, *, is_banned=False):
    """Wire up admin_supabase.table("user_profiles").select(...).eq(...).limit(...).execute()"""
    data = [{"is_banned": is_banned}]
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .limit.return_value.execute.return_value
    ) = make_supabase_result(data)


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

async def test_missing_authorization_header_raises_401():
    request = make_request({})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing Authorization header"


async def test_malformed_header_no_bearer_scheme_raises_401():
    request = make_request({"Authorization": "Basic abc123"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Authorization header format"


async def test_malformed_header_missing_token_raises_401():
    # Only one part -- no token after "Bearer"
    request = make_request({"Authorization": "Bearer"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Authorization header format"


async def test_malformed_header_too_many_parts_raises_401():
    request = make_request({"Authorization": "Bearer abc extra"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid Authorization header format"


# ---------------------------------------------------------------------------
# Cache hit path
# ---------------------------------------------------------------------------

async def test_cache_hit_skips_supabase_get_user_and_returns_user_id(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    configure_ban_check(fake_supabase, is_banned=False)

    token = "cached-token-123"
    cache_token_user(token, "user-from-cache")

    request = make_request({"Authorization": f"Bearer {token}"})
    user_id = await verify_user_token(request)

    assert user_id == "user-from-cache"
    fake_supabase.auth.get_user.assert_not_called()


# ---------------------------------------------------------------------------
# Cache miss + Supabase validation
# ---------------------------------------------------------------------------

async def test_cache_miss_valid_token_validates_and_caches_result(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    configure_ban_check(fake_supabase, is_banned=False)
    fake_supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-from-supabase")
    )

    token = "fresh-token-456"
    request = make_request({"Authorization": f"Bearer {token}"})
    user_id = await verify_user_token(request)

    assert user_id == "user-from-supabase"
    fake_supabase.auth.get_user.assert_called_once_with(token)
    # Result should now be cached for subsequent requests.
    assert get_cached_user_by_token(token) == "user-from-supabase"


async def test_invalid_token_no_user_on_response_raises_401(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user.return_value = SimpleNamespace(user=None)

    request = make_request({"Authorization": "Bearer bad-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


async def test_invalid_token_falsy_response_raises_401(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user.return_value = None

    request = make_request({"Authorization": "Bearer bad-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


async def test_expired_token_exception_raises_401_token_expired(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user.side_effect = Exception("JWT expired at 2026-01-01")

    request = make_request({"Authorization": "Bearer expired-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token expired"


async def test_generic_supabase_exception_raises_401_invalid_token(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user.side_effect = Exception("network unreachable")

    request = make_request({"Authorization": "Bearer some-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


# ---------------------------------------------------------------------------
# Ban enforcement
# ---------------------------------------------------------------------------

async def test_banned_user_raises_403(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    configure_ban_check(fake_supabase, is_banned=True)
    fake_supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="banned-user")
    )

    request = make_request({"Authorization": "Bearer banned-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Your account has been banned"


async def test_non_banned_user_passes_through(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    configure_ban_check(fake_supabase, is_banned=False)
    fake_supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="good-user")
    )

    request = make_request({"Authorization": "Bearer good-token"})
    user_id = await verify_user_token(request)
    assert user_id == "good-user"


async def test_ban_status_cache_hit_skips_db_query(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-with-cached-ban")
    )
    cache_ban_status("user-with-cached-ban", True)

    request = make_request({"Authorization": "Bearer some-token"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_user_token(request)
    assert exc_info.value.status_code == 403
    fake_supabase.table.assert_not_called()


async def test_ban_check_fails_open_on_db_exception(patch_supabase, fake_supabase):
    """If the ban-status DB lookup errors, the user is treated as not banned
    (fail open) so a transient DB issue never locks everyone out."""
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.table.side_effect = Exception("db unavailable")
    fake_supabase.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-during-outage")
    )

    request = make_request({"Authorization": "Bearer some-token"})
    user_id = await verify_user_token(request)
    assert user_id == "user-during-outage"


# ---------------------------------------------------------------------------
# get_user_id_from_body_or_token
# ---------------------------------------------------------------------------

def test_get_user_id_from_body_or_token_no_body_id_returns_token_id():
    assert get_user_id_from_body_or_token(None, "token-user") == "token-user"


def test_get_user_id_from_body_or_token_matching_ids_returns_id():
    assert get_user_id_from_body_or_token("same-id", "same-id") == "same-id"


def test_get_user_id_from_body_or_token_mismatch_raises_403():
    with pytest.raises(HTTPException) as exc_info:
        get_user_id_from_body_or_token("body-user", "token-user")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "User ID mismatch: cannot act on behalf of another user"


def test_get_user_id_from_body_or_token_empty_string_body_returns_token_id():
    # Empty string is falsy, so it should fall back to the token's user_id
    # rather than being treated as a mismatch.
    assert get_user_id_from_body_or_token("", "token-user") == "token-user"


# ---------------------------------------------------------------------------
# Event-loop safety
#
# FastAPI runs `def` ENDPOINTS in a threadpool but always runs `async def`
# DEPENDENCIES on the event loop. `verify_user_token` is such a dependency and
# guards nearly every route, so a synchronous Supabase round trip inside it
# freezes the whole worker — every other user's request included.
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def loop_ticks():
    """Count event-loop turns while the block runs. Zero means it was blocked."""
    counter = {"ticks": 0}

    async def ticker():
        while True:
            await asyncio.sleep(0.01)
            counter["ticks"] += 1

    beat = asyncio.create_task(ticker())
    try:
        yield counter
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


def slow_get_user(user_id="user-slow", delay=0.2):
    def _lookup(_token):
        time.sleep(delay)
        return SimpleNamespace(user=SimpleNamespace(id=user_id))
    return _lookup


@pytest.mark.asyncio
async def test_token_validation_does_not_block_the_event_loop(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user = slow_get_user("user-slow")
    configure_ban_check(fake_supabase, is_banned=False)

    async with loop_ticks() as counter:
        user_id = await verify_user_token(make_request({"Authorization": "Bearer cold-token"}))

    assert user_id == "user-slow"
    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_ban_lookup_does_not_block_the_event_loop(patch_supabase, fake_supabase):
    patch_supabase("auth_middleware", admin=fake_supabase)
    cache_token_user("warm-token", "user-warm")

    def slow_ban_check():
        time.sleep(0.2)
        return make_supabase_result([{"is_banned": False}])

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .limit.return_value.execute
    ) = slow_ban_check

    async with loop_ticks() as counter:
        user_id = await verify_user_token(make_request({"Authorization": "Bearer warm-token"}))

    assert user_id == "user-warm"
    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_optional_user_lookup_does_not_block_the_event_loop(patch_supabase, fake_supabase):
    """The storefront personalises anonymous-friendly pages through this."""
    from auth_middleware import get_optional_user_id

    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user = slow_get_user("browser-1")

    request = SimpleNamespace(headers={"Authorization": "Bearer cold-browse"}, query_params={})

    async with loop_ticks() as counter:
        user_id = await get_optional_user_id(request)

    assert user_id == "browser-1"
    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_optional_user_lookup_ignores_a_token_in_the_query_string(patch_supabase, fake_supabase):
    """SPEC-056 #6. A credential in a URL ends up in every log that touches it,
    so the only place a bearer token is read from is the header."""
    from auth_middleware import get_optional_user_id

    patch_supabase("auth_middleware", admin=fake_supabase)
    fake_supabase.auth.get_user = slow_get_user("browser-1")

    request = SimpleNamespace(headers={}, query_params={"token": "a-real-access-token"})

    assert await get_optional_user_id(request) is None
