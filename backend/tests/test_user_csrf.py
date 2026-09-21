"""
CSRF on the buyer surface — SPEC-093.

Moving the buyer from `Authorization: Bearer` to a cookie is what creates this
exposure: a bearer token is never auto-sent cross-site, a cookie always is. So
every mutating buyer endpoint now double-submits a CSRF token, and these tests
are the proof that the gate is actually wired to the routes rather than merely
available to them.

The two carve-outs are deliberate and tested here too: a bearer-authenticated
call needs no CSRF token (nothing auto-sends it), and the Stripe webhook is
authenticated by signature and must never be asked for one.
"""

import time

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from core.csrf import USER_SCOPE, generate_csrf_token, verify_user_csrf_token
from core.env import USER_COOKIE_NAME
from domains.identity.user_session import create_session

# Every mutating buyer route, and the method that mutates. If a route is added
# without a CSRF dependency, `test_every_mutating_buyer_route_is_gated` fails.
MUTATING_BUYER_ROUTES = [
    ("POST", "/chat/stream"),
    ("POST", "/chat/read"),
    ("POST", "/chat/typing"),
    ("DELETE", "/chat/history/buyer-1"),
    ("POST", "/payment/checkout"),
    ("POST", "/payment/confirm-payment"),
    ("PUT", "/user/buyer-1/password"),
    ("PUT", "/user/buyer-1/email"),
    ("PUT", "/user/buyer-1/language"),
    ("PUT", "/user/buyer-1/profile"),
    ("DELETE", "/user/buyer-1"),
]


@pytest.fixture
def session_cookie():
    """A live buyer session, and the CSRF token that belongs to it."""
    sid = create_session("buyer-1", "access-1", "refresh-1", int(time.time()) + 3600)
    return sid, generate_csrf_token(sid, USER_SCOPE)


@pytest.mark.parametrize(("method", "path"), MUTATING_BUYER_ROUTES)
async def test_every_mutating_buyer_route_is_gated(client, session_cookie, method, path):
    sid, _token = session_cookie

    res = await client.request(method, path, cookies={USER_COOKIE_NAME: sid})

    assert res.status_code == 403, f"{method} {path} accepted a cookie-authenticated call with no CSRF token"
    assert "CSRF" in res.json()["detail"]


@pytest.mark.parametrize(("method", "path"), MUTATING_BUYER_ROUTES)
async def test_a_wrong_token_is_as_good_as_none(client, session_cookie, method, path):
    sid, _token = session_cookie

    res = await client.request(
        method, path, cookies={USER_COOKIE_NAME: sid}, headers={"X-CSRF-Token": "not-the-token"}
    )

    assert res.status_code == 403


async def test_the_matching_token_passes_the_gate(client, session_cookie, patch_supabase, fake_supabase):
    """The positive path, end to end: cookie in, CSRF echoed, handler runs."""
    sid, token = session_cookie
    patch_supabase("domains.negotiation.routes", admin=fake_supabase)

    res = await client.post("/chat/read", cookies={USER_COOKIE_NAME: sid}, headers={"X-CSRF-Token": token})

    assert res.status_code == 200
    stamped = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert stamped["user_id"] == "buyer-1"


async def test_a_token_from_another_session_is_rejected(client, session_cookie):
    """Tokens are bound to their session, not to the browser."""
    sid, _token = session_cookie
    other_sid = create_session("buyer-2", "a", "r", int(time.time()) + 3600)
    other_token = generate_csrf_token(other_sid, USER_SCOPE)

    res = await client.post("/chat/read", cookies={USER_COOKIE_NAME: sid}, headers={"X-CSRF-Token": other_token})

    assert res.status_code == 403


async def test_a_bearer_call_needs_no_csrf_token(client, auth_user, patch_supabase, fake_supabase):
    """The eval harness and the test-suite still authenticate this way, and a
    header no browser auto-sends is not forgeable cross-site."""
    auth_user("buyer-1")
    patch_supabase("domains.negotiation.routes", admin=fake_supabase)

    res = await client.post("/chat/read", headers={"Authorization": "Bearer some-token"})

    assert res.status_code == 200


async def test_safe_methods_are_exempt(client, session_cookie, auth_user):
    sid, _token = session_cookie
    auth_user("buyer-1")

    res = await client.get("/chat/settings/buyer-1", cookies={USER_COOKIE_NAME: sid})

    assert res.status_code != 403


async def test_the_stripe_webhook_is_not_csrf_gated(client, session_cookie):
    """Signature-authenticated, server-to-server, and no cookie of ours — asking
    Stripe for a CSRF token would simply break payments."""
    sid, _token = session_cookie

    res = await client.post(
        "/payment/webhook/stripe",
        cookies={USER_COOKIE_NAME: sid},
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=nope"},
    )

    assert res.status_code != 403


async def test_a_session_whose_csrf_token_expired_is_told_to_log_in_again(client):
    """The Redis token can outlive its cookie or vice versa; the message has to
    be actionable rather than a bare 403."""
    from core.cache import redis_client

    sid = create_session("buyer-1", "a", "r", int(time.time()) + 3600)
    generate_csrf_token(sid, USER_SCOPE)
    redis_client.delete(f"{USER_SCOPE.redis_prefix}{sid}")

    res = await client.post("/chat/read", cookies={USER_COOKIE_NAME: sid}, headers={"X-CSRF-Token": "anything"})

    assert res.status_code == 403
    assert "log in again" in res.json()["detail"]


async def test_the_admin_and_buyer_csrf_scopes_do_not_share_a_cookie():
    """An operator is signed in as both, in one browser, on one domain."""
    from core.csrf import ADMIN_SCOPE

    assert ADMIN_SCOPE.cookie_name != USER_SCOPE.cookie_name
    assert ADMIN_SCOPE.session_cookie != USER_SCOPE.session_cookie
    assert ADMIN_SCOPE.redis_prefix != USER_SCOPE.redis_prefix


async def test_the_gate_is_a_no_op_for_an_anonymous_caller():
    """No session cookie means nothing to forge against; the auth dependency,
    not this one, is what turns the request away."""
    app = FastAPI()

    @app.post("/probe", dependencies=[Depends(verify_user_csrf_token)])
    def probe():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/probe")

    assert res.status_code == 200
