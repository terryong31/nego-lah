"""Turnstile guards the one unauthenticated credential endpoint. (SPEC-044 D)

`core/security.py:verify_turnstile` was fully written, fully tested, and a
dependency of zero routes — a security control that existed only as code. The
frontend's Turnstile tokens go to Supabase Auth (`options.captchaToken`) on
sign-up and sign-in, so account creation is gated; the backend's own verifier
protected nothing.

`POST /admin/auth/login` is where it belongs. It is the only unauthenticated,
brute-forceable credential route in the system — and the one whose per-IP login
throttle was bypassable by rotating `X-Forwarded-For` until this week's
`client_ip` fix. Conference attendees never touch the console, so gating it
costs them nothing.

**The availability trade is deliberate.** `verify_turnstile` used to turn an
unreachable Cloudflare into a 500. On this route that means a Cloudflare
outage locks the operator out of the admin console — including out of the
takeover the AI hands conversations to when it retires from a chat. So a
*transport* failure now fails open, while a returned verdict of "not a human"
still fails closed. An attacker can't induce the former, and the route still
has a password, an emailed OTP, and rate limiting under it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from core.security import verify_turnstile

# --- the route is actually gated ---------------------------------------------

def test_admin_login_depends_on_turnstile():
    """Asserted against the route's dependency list rather than by driving a
    request, because the interesting failure is the control silently not being
    wired — which is exactly what a passing request-level test looks like when
    the dev-mode bypass is active."""
    from main import app

    # `include_router` keeps each router as a `_IncludedRouter` node holding the
    # real one under `original_router`, so the app's routes are a tree. Each
    # route also stores its own path without the prefix it was mounted under —
    # hence `/auth/login` here rather than the `/admin/auth/login` a client
    # calls.
    def walk(routes):
        for route in routes:
            yield route
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from walk(nested.routes)

    login = next(
        route for route in walk(app.routes)
        if getattr(route, "path", None) == "/auth/login"
        and "POST" in getattr(route, "methods", set())
    )
    dependency_calls = [d.call for d in login.dependant.dependencies]

    assert verify_turnstile in dependency_calls


async def test_admin_login_still_works_without_a_token_in_development(
    client, monkeypatch
):
    """The dev bypass is what keeps local development from needing a widget and
    a Cloudflare account. It has to survive the route being gated."""
    monkeypatch.setattr(
        "routes.admin.auth.enforce_login_rate_limit", lambda email, ip: None
    )
    monkeypatch.setattr(
        "routes.admin.auth.password_then_send_otp", lambda email, pw: "handle-123"
    )

    resp = await client.post(
        "/admin/auth/login",
        json={"email": "admin@example.com", "password": "hunter2"},
    )

    assert resp.status_code == 200
    assert resp.json()["handle"] == "handle-123"


# --- fail closed on a verdict, open on an outage -----------------------------

@pytest.fixture
def prod_turnstile(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret-key")


async def test_a_rejected_token_is_refused(prod_turnstile):
    """Cloudflare answered, and the answer was "no". That is a verdict."""
    response = MagicMock(status_code=200)
    response.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = response
        with pytest.raises(HTTPException) as exc:
            await verify_turnstile(x_turnstile_token="a-token")

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("no route to host"),
        httpx.ReadTimeout("siteverify took too long"),
        httpx.RemoteProtocolError("connection closed"),
    ],
    ids=["connect-error", "timeout", "protocol-error"],
)
async def test_an_unreachable_cloudflare_does_not_lock_the_operator_out(
    prod_turnstile, failure
):
    """No verdict was returned, so there is nothing to fail closed on. Refusing
    here would mean a Cloudflare outage takes the admin console down with it,
    and the console is what the AI hands conversations to."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.side_effect = failure
        assert await verify_turnstile(x_turnstile_token="a-token") is True


async def test_a_malformed_siteverify_body_is_treated_as_an_outage(prod_turnstile):
    """A response that isn't JSON is Cloudflare misbehaving, not a verdict."""
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("not json")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = response
        assert await verify_turnstile(x_turnstile_token="a-token") is True


async def test_a_missing_token_is_still_refused_outright(prod_turnstile):
    """Fail-open covers Cloudflare being unreachable — not a caller who never
    solved a challenge. This one never gets as far as the network."""
    with pytest.raises(HTTPException) as exc:
        await verify_turnstile(x_turnstile_token=None)

    assert exc.value.status_code == 400


async def test_a_missing_secret_is_still_a_server_error(prod_turnstile, monkeypatch):
    """Fail-open must not paper over our own misconfiguration: a production
    deploy with no secret key is broken and should say so loudly."""
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        await verify_turnstile(x_turnstile_token="a-token")

    assert exc.value.status_code == 500
