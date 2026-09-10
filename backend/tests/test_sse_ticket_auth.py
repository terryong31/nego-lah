"""SSE connections are authorised by a short-lived ticket, not the access token.

SPEC-056 #6. `EventSource` cannot set an `Authorization` header, so the stream
took the Supabase access token in the query string instead. A query string is
the least private part of a request: it is written verbatim into the reverse
proxy's access log, the CDN's, any APM breadcrumb, the browser's history and the
`Referer` of anything the page loads next. A token good for the next hour of that
account's API calls should not be in any of them.

A ticket fixes the exposure without giving up EventSource: it is worth one
connection, for thirty seconds, and reveals nothing about the session that
minted it. The token itself travels in the header, on the POST that mints it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from cache import mint_sse_ticket, redeem_sse_ticket
from routes.chat import notifications_stream


def test_a_ticket_is_redeemable_exactly_once():
    ticket = mint_sse_ticket("user-1")

    assert redeem_sse_ticket(ticket) == "user-1"
    assert redeem_sse_ticket(ticket) is None, "a replayed ticket must not authorise a second stream"


def test_an_unknown_ticket_redeems_to_nobody():
    assert redeem_sse_ticket("never-minted") is None
    assert redeem_sse_ticket("") is None


def test_tickets_are_unguessable_and_distinct():
    tickets = {mint_sse_ticket("user-1") for _ in range(20)}
    assert len(tickets) == 20
    assert all(len(t) >= 32 for t in tickets)


def test_a_ticket_expires():
    from cache import SSE_TICKET_TTL, redis_client

    ticket = mint_sse_ticket("user-1")
    assert 0 < redis_client.ttl(f"sse:ticket:{ticket}") <= SSE_TICKET_TTL
    assert SSE_TICKET_TTL <= 60, "a ticket sitting in a log for minutes defeats the point"


def test_a_ticket_does_not_contain_the_access_token():
    """It is a lookup key, not an encoding of the session."""
    ticket = mint_sse_ticket("user-1")
    assert "user-1" not in ticket


# ---------------------------------------------------------------------------
# The endpoints
# ---------------------------------------------------------------------------

async def test_mint_endpoint_requires_a_bearer_token(client):
    res = await client.post("/chat/notifications/ticket")
    assert res.status_code == 401


async def test_mint_endpoint_returns_a_redeemable_ticket(client, auth_user):
    auth_user("user-sse-mint")

    res = await client.post("/chat/notifications/ticket")

    assert res.status_code == 200
    body = res.json()
    assert body["expires_in"] > 0
    assert redeem_sse_ticket(body["ticket"]) == "user-sse-mint"


# The stream handler is driven directly rather than through the ASGI client:
# a successful connection is an open-ended SSE body, so a client request that
# is wrongly *allowed* would hang the suite instead of failing it.

def _stream_request(**query):
    request = MagicMock()
    request.headers = {}
    request.query_params = query
    request.is_disconnected = AsyncMock(return_value=False)
    return request


async def test_the_stream_no_longer_accepts_an_access_token_in_the_url(monkeypatch):
    """The whole point: leaving `?token=` working would leave the leak open."""
    monkeypatch.setattr("cache.get_cached_user_by_token", lambda _t: "user-sse-1")

    with pytest.raises(HTTPException) as exc:
        await notifications_stream(_stream_request(token="a-real-access-token"))

    assert exc.value.status_code == 401


async def test_the_stream_rejects_a_missing_unknown_or_reused_ticket():
    for query in ({}, {"ticket": "not-a-real-ticket"}):
        with pytest.raises(HTTPException) as exc:
            await notifications_stream(_stream_request(**query))
        assert exc.value.status_code == 401

    ticket = mint_sse_ticket("user-sse-2")
    redeem_sse_ticket(ticket)  # spend it
    with pytest.raises(HTTPException) as exc:
        await notifications_stream(_stream_request(ticket=ticket))
    assert exc.value.status_code == 401


async def test_the_stream_opens_for_a_fresh_ticket():
    from notifications import notification_broker

    ticket = mint_sse_ticket("user-sse-3")
    response = await notifications_stream(_stream_request(ticket=ticket))
    assert response.status_code == 200

    gen = response.body_iterator
    assert await gen.__anext__() == ": connected\n\n"
    assert notification_broker.has_subscribers("user-sse-3") is True
    await gen.aclose()


async def test_a_ticket_is_spent_by_connecting():
    """One ticket, one stream — a copy lifted from a log is already useless."""
    ticket = mint_sse_ticket("user-sse-4")

    response = await notifications_stream(_stream_request(ticket=ticket))
    await response.body_iterator.aclose()

    with pytest.raises(HTTPException) as exc:
        await notifications_stream(_stream_request(ticket=ticket))
    assert exc.value.status_code == 401
