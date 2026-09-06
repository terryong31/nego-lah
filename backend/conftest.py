"""
Shared pytest fixtures + safety rails for the whole backend test suite.

READ THIS BEFORE WRITING TESTS.

1. ENVIRONMENT SAFETY
   This file sets every sensitive env var to a fake value *before* any
   application module is imported (module-level code below runs the moment
   pytest loads this conftest, which always happens before it imports any
   test file). `env.py` calls `load_dotenv(...)` with the default
   `override=False`, so a real `backend/.env` (real Supabase project, real
   Stripe keys, a real managed Redis) can NEVER clobber what's set here.
   `VERCEL=1` additionally forces `env.REDIS_URL` to stay `None` no matter
   what's on the developer's machine, so `cache.py` always falls back to its
   in-memory fake Redis — tests never touch a real Redis, local or remote.
   Do not add real credentials to this file. Do not delete these lines.

2. MOCKING SEAMS (see backend structural map for the full rationale)
   - Supabase: modules do `from connector import admin_supabase` /
     `user_supabase` at import time, so patching `connector.admin_supabase`
     after that import already happened does nothing for that module. Patch
     the name on the *consuming* module instead, e.g.
     `monkeypatch.setattr("items.admin_supabase", fake_supabase)`. Use the
     `patch_supabase` fixture below for this.
   - A plain `MagicMock()` already supports arbitrary chained calls
     (`.table("items").select("*").eq("id", x).execute()` all "just work" and
     return further MagicMocks), so `fake_supabase` fixture is deliberately a
     bare MagicMock. Configure the terminal `.execute()` return value via
     `make_supabase_result(...)`, e.g.:
       mock.table.return_value.select.return_value.eq.return_value.execute.return_value = \\
           make_supabase_result([{"id": "1", "name": "Widget"}])
   - Stripe: every payment module does `import stripe` and calls it directly
     (no wrapper/client object) — use the `fake_stripe` fixture, which
     monkeypatches the handful of Stripe SDK entry points this codebase
     actually calls, and returns the (patched) `stripe` module so you can set
     `.return_value` / `.side_effect` per test.
   - Auth dependencies: most routes gate on `Depends(verify_user_token)` /
     `Depends(verify_admin)` — use the `auth_user` / `admin_user` fixtures,
     which use FastAPI's `app.dependency_overrides` (keyed by the callable
     object itself, so it doesn't matter which module name aliased it).
     EXCEPTION: `routes/chat.py`'s `/chat/stream` calls
     `await verify_user_token(request)` directly inside the handler body, NOT
     via `Depends(...)` — `dependency_overrides` has no effect there. For
     that endpoint, monkeypatch the name where it's *called* instead:
     `monkeypatch.setattr("routes.chat.verify_user_token", fake_async_fn)`.
   - LLM / LangChain agents (`agent/bot.py`, `agent/sub_agents/*`,
     `agent/tools/image_analyzer.py`, `agent/tools/market_price.py`): there is
     no single seam because each module constructs its own
     `ChatGoogleGenerativeAI` differently (lazy singleton in `bot.py`, eager
     module-level singleton elsewhere). Monkeypatch the specific
     `_get_model` / `_get_customer_agent` functions in `bot.py`, or the
     `.ainvoke` / `.invoke` / `.astream` method on the already-constructed
     singleton object in the sub-agent/tool modules. Don't try to mock the
     `ChatGoogleGenerativeAI` class globally — patch call sites.
   - Rate limiting: `cache.check_rate_limit` is the real gate on
     `/chat/stream` and admin login/OTP. Give each test a distinct
     user_id/email/IP, or monkeypatch `check_rate_limit` to always return
     `True` at whichever module actually calls it (check the import style in
     that file — some do `from cache import check_rate_limit`, others call
     `cache.check_rate_limit(...)` qualified).

3. Every test gets a clean slate automatically: the in-memory fake Redis is
   flushed after each test, and FastAPI's `dependency_overrides` are cleared
   after each test — you don't need to do this yourself.
"""

import os

# --- 1. Environment safety (see module docstring) --------------------------
_TEST_ENV = {
    "SUPABASE_URL": "https://test-project.supabase.co",
    "ADMIN_SUPABASE_KEY": "test-admin-service-role-key",
    "USER_SUPABASE_KEY": "test-user-anon-key",
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "GEMINI_API_KEY": "test-gemini-api-key",
    # SPEC-020 hybrid router. Pinned to "gemini" so the suite is hermetic: with
    # "auto" (the production default) the health probe would fire a real HTTP
    # request at LOCAL_LLM_BASE_URL, and on a machine where the local-llm MLX
    # server IS running (this is that machine) tests would silently start
    # routing at, and generating from, the real 35B model. Tests that exercise
    # local routing opt back in explicitly via monkeypatch.setenv + a patched probe.
    "LLM_PROVIDER": "gemini",
    "LOCAL_LLM_BASE_URL": "http://127.0.0.1:8001/v1",
    "STRIPE_API_KEY": "sk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_dummy",
    "RESEND_API_KEY": "re_test_dummy",
    "RESEND_WEBHOOK_SECRET": "whsec_resend_dummy",
    "RESEND_FORWARD_TO": "forward-to@example.com",
    "RESEND_FORWARD_FROM": "noreply@example.com",
    "RESEND_ALLOWED_RECIPIENTS": "support@example.com",
    "FRONTEND_URL": "http://localhost:3000",
    "ADMIN_COOKIE_NAME": "admin_sid",
    # Secure=false so httpx's cookiejar will actually round-trip the admin
    # session cookie over the test client's http://test base_url.
    "ADMIN_COOKIE_SECURE": "false",
    "ADMIN_COOKIE_SAMESITE": "strict",
    "ADMIN_COOKIE_PATH": "/",
    "ADMIN_SESSION_TTL": "7200",
    "ADMIN_PREAUTH_TTL": "300",
    "STORAGE_BUCKET": "test-images",
    "ENV": "test",
    "DISABLE_PAYMENT_CLEANUP": "1",
    "VERCEL": "1",
    # Explicitly pinned to "" (NOT simply unset/popped): env.py calls
    # load_dotenv(override=False) on backend/.env, which — on this and any
    # other developer machine that has a real backend/.env — DOES contain a
    # real REDIS_URL. load_dotenv only fills in keys that are currently
    # *absent* from os.environ, so merely popping these would leave them
    # unset here and get them silently refilled with the real value the
    # moment env.py imports, connecting every test run to a real Redis
    # server. Setting them to "" makes them present-but-falsy, which
    # load_dotenv leaves alone, and which env.py's own `if not REDIS_URL`
    # checks treat the same as unset. This was the root cause of an
    # intermittent flake where TTL-expiry tests (which mock Python's
    # time.time(), meaningless against a real Redis's own server-side clock)
    # failed non-deterministically depending on real elapsed wall-clock time.
    "REDIS_URL": "",
    "REDIS_HOST": "",
    "REDIS_PORT": "",
    "REDIS_PASSWORD": "",
    "REDIS_USERNAME": "",
    "REDIS_SSL": "",
    "SENTRY_DSN": "",
    "CORS_ORIGINS": "",
    "TURNSTILE_SECRET_KEY": "",
    "TURNSTILE_SECRET": "",
}
os.environ.update(_TEST_ENV)

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


# --- 2. FastAPI app + HTTP client -------------------------------------------
@pytest.fixture
def app():
    from main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    from main import app as fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _flush_in_memory_redis():
    yield
    import cache

    # Self-healing safety net: VERCEL=1 (set above) guarantees cache.redis_client
    # should always be the in-memory fake in tests. If a test ever leaves it
    # pointed at a real Redis connection (this machine happens to run one
    # locally for app dev — a rare timing/race scenario was observed once
    # during development of this suite but was not reliably reproducible),
    # force it back rather than let a real client silently leak into later
    # tests' TTL/expiry assertions (which mock Python's time.time(), not
    # Redis's own server-side clock, and would then fail confusingly).
    if not isinstance(cache.redis_client, cache._InMemoryRedis):
        cache.redis_client = cache._InMemoryRedis()
        return
    for key in list(cache.redis_client.keys("*")):
        cache.redis_client.delete(key)


# --- 3. Auth override fixtures ----------------------------------------------
@pytest.fixture
def auth_user(app):
    """Bypass `Depends(verify_user_token)` for routes that use it, returning a fixed user_id."""
    from auth_middleware import verify_user_token

    def _apply(user_id="test-user-id"):
        app.dependency_overrides[verify_user_token] = lambda: user_id
        return user_id

    return _apply


@pytest.fixture
def admin_user(app):
    """Bypass `Depends(verify_admin)` for the /admin/* protected router."""
    from admin_session import verify_admin

    def _apply(user_id="test-admin-id", email="admin@example.com", ip="127.0.0.1"):
        session = {"user_id": user_id, "email": email, "ip": ip}
        app.dependency_overrides[verify_admin] = lambda: session
        return session

    return _apply


# --- 4. Supabase mocking helpers --------------------------------------------
def make_supabase_result(data=None, count=None):
    """Build a fake postgrest-style response object with `.data` (and optional `.count`)."""
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count
    return result


@pytest.fixture
def fake_supabase():
    """A fresh chainable MagicMock per test — see module docstring for usage."""
    return MagicMock()


@pytest.fixture
def patch_supabase(monkeypatch):
    """patch_supabase("items", admin=fake, user=fake2) patches `<module>.admin_supabase` /
    `<module>.user_supabase` on the given already-imported module name (import path relative
    to backend/, e.g. "items", "routes.admin.users", "agent.tools.items")."""
    import importlib

    def _patch(module_name, *, admin=None, user=None):
        mod = importlib.import_module(module_name)
        if admin is not None:
            monkeypatch.setattr(mod, "admin_supabase", admin, raising=False)
        if user is not None:
            monkeypatch.setattr(mod, "user_supabase", user, raising=False)
        return mod

    return _patch


# --- 5. Stripe mocking -------------------------------------------------------
@pytest.fixture
def fake_stripe(monkeypatch):
    """Patches every Stripe SDK entry point this codebase actually calls with a MagicMock,
    and returns the (patched) `stripe` module so tests can set .return_value/.side_effect."""
    import stripe

    for target, name in (
        (stripe.checkout.Session, "create"),
        (stripe.checkout.Session, "retrieve"),
        (stripe.Refund, "create"),
        (stripe.PaymentLink, "create"),
        (stripe.PaymentLink, "modify"),
        (stripe.PaymentLink, "retrieve"),
        (stripe.Product, "create"),
        (stripe.Product, "modify"),
        (stripe.Price, "create"),
        (stripe.Webhook, "construct_event"),
    ):
        monkeypatch.setattr(target, name, MagicMock())
    return stripe
