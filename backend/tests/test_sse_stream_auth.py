"""The notification stream carries no credential in its URL — SPEC-056 #6, SPEC-094.

`EventSource` cannot set an `Authorization` header, so this stream originally
took the Supabase access token in the query string: the least private part of a
request, written verbatim into the reverse proxy's access log, the CDN's, any APM
breadcrumb, the browser's history and the `Referer` of anything the page loads
next. SPEC-056 #6 replaced it with a single-use 30-second ticket.

SPEC-093 removed the need for either. The session is a cookie now, and a browser
attaches it to `EventSource(url, {withCredentials: true})` unprompted — so the
URL carries nothing at all, and there is no ticket left to leak, replay or
expire. What these tests protect is that property: the stream authenticates from
credentials the URL never sees.

The handler is driven directly rather than through the ASGI client, because a
successful connection is an open-ended SSE body — a request that was wrongly
allowed would hang the suite instead of failing it.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from core.env import USER_COOKIE_NAME
from domains.identity.auth_middleware import verify_user_token
from domains.identity.user_session import create_session
from domains.negotiation.routes import notifications_stream


def _stream_request(cookies=None, headers=None, **query):
    request = MagicMock()
    request.headers = headers or {}
    request.cookies = cookies or {}
    request.query_params = query
    request.is_disconnected = AsyncMock(return_value=False)
    return request


async def _open(request):
    """Resolve auth the way FastAPI's Depends would, then call the handler."""
    user_id = await verify_user_token(request)
    return await notifications_stream(request, user_id)


# ---------------------------------------------------------------------------
# What the URL may not carry
# ---------------------------------------------------------------------------


async def test_a_token_in_the_query_string_authorises_nothing(monkeypatch):
    """Leaving `?token=` working would leave the original leak open. Even a token
    the cache would happily resolve is not a credential when it is in the URL."""
    monkeypatch.setattr(
        "domains.identity.auth_middleware.get_cached_user_by_token", lambda _t: "user-sse-1"
    )

    with pytest.raises(HTTPException) as exc:
        await _open(_stream_request(token="a-real-access-token"))

    assert exc.value.status_code == 401


async def test_a_ticket_in_the_query_string_authorises_nothing():
    """The ticket mechanism is gone, not merely unused."""
    with pytest.raises(HTTPException) as exc:
        await _open(_stream_request(ticket="anything-at-all"))

    assert exc.value.status_code == 401


async def test_an_unauthenticated_request_is_refused():
    with pytest.raises(HTTPException) as exc:
        await _open(_stream_request())

    assert exc.value.status_code == 401


async def test_the_ticket_endpoint_is_gone(client):
    res = await client.post("/chat/notifications/ticket")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# What does authorise it
# ---------------------------------------------------------------------------


async def test_the_session_cookie_opens_the_stream(patch_supabase, fake_supabase):
    from conftest import make_supabase_result
    from core.notifications import notification_broker

    patch_supabase("domains.identity.auth_middleware", admin=fake_supabase)
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"is_banned": False}])

    sid = create_session("user-sse-3", "access-1", "refresh-1", int(time.time()) + 3600)
    response = await _open(_stream_request(cookies={USER_COOKIE_NAME: sid}))

    assert response.status_code == 200
    gen = response.body_iterator
    assert await gen.__anext__() == ": connected\n\n"
    assert notification_broker.has_subscribers("user-sse-3") is True
    await gen.aclose()


async def test_a_revoked_session_cannot_open_the_stream():
    from core.cache import redis_client
    from domains.identity.user_session import _SESS_KEY

    sid = create_session("user-sse-4", "access-1", "refresh-1", int(time.time()) + 3600)
    redis_client.delete(f"{_SESS_KEY}{sid}")

    with pytest.raises(HTTPException) as exc:
        await _open(_stream_request(cookies={USER_COOKIE_NAME: sid}))

    assert exc.value.status_code == 401


async def test_a_bearer_token_still_opens_the_stream(monkeypatch, patch_supabase, fake_supabase):
    """Not a browser path — the harness and any server-to-server consumer."""
    from conftest import make_supabase_result
    from core.notifications import notification_broker

    monkeypatch.setattr(
        "domains.identity.auth_middleware.get_cached_user_by_token", lambda _t: "user-sse-5"
    )
    patch_supabase("domains.identity.auth_middleware", admin=fake_supabase)
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"is_banned": False}])

    response = await _open(_stream_request(headers={"Authorization": "Bearer harness-token"}))

    assert response.status_code == 200
    gen = response.body_iterator
    assert await gen.__anext__() == ": connected\n\n"
    assert notification_broker.has_subscribers("user-sse-5") is True
    await gen.aclose()


async def test_the_stream_unsubscribes_when_the_client_goes_away():
    from core.notifications import notification_broker, sse_stream

    request = _stream_request()
    response = sse_stream("user-sse-6", request)
    gen = response.body_iterator
    await gen.__anext__()
    assert notification_broker.has_subscribers("user-sse-6") is True

    await gen.aclose()
    assert notification_broker.has_subscribers("user-sse-6") is False
