import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import importlib
import json
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

import main
from main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

@pytest.mark.asyncio
async def test_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Second-Hand Store API", "status": "running"}


# ---------------------------------------------------------------------------
# CORS_ORIGINS env parsing
#
# main.py reads CORS_ORIGINS at *module import time*, so we have to
# importlib.reload(main) after monkeypatching the env var to observe the
# effect. Each test restores the env var (monkeypatch.undo()) and reloads
# main() again *inside* the test (in a finally block) so the module is back
# to its baseline configuration before the next test runs -- other tests in
# this file rely on a `main.app` that reflects the conftest baseline env.
# ---------------------------------------------------------------------------

def _reload_main():
    return importlib.reload(main)


@pytest.mark.asyncio
async def test_cors_origins_json_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", json.dumps(["https://json-allowed.example.com"]))
    try:
        reloaded = _reload_main()
        async with AsyncClient(transport=ASGITransport(app=reloaded.app), base_url="http://test") as ac:
            allowed = await ac.get("/", headers={"Origin": "https://json-allowed.example.com"})
            blocked = await ac.get("/", headers={"Origin": "https://not-allowed.example.com"})
        assert allowed.headers.get("access-control-allow-origin") == "https://json-allowed.example.com"
        assert "access-control-allow-origin" not in blocked.headers
    finally:
        monkeypatch.undo()
        _reload_main()


@pytest.mark.asyncio
async def test_cors_origins_comma_separated_fallback(monkeypatch):
    # Not valid JSON -> json.loads raises -> falls back to str.split(",")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    try:
        reloaded = _reload_main()
        async with AsyncClient(transport=ASGITransport(app=reloaded.app), base_url="http://test") as ac:
            resp_a = await ac.get("/", headers={"Origin": "https://a.example.com"})
            resp_b = await ac.get("/", headers={"Origin": "https://b.example.com"})
            resp_other = await ac.get("/", headers={"Origin": "https://other.example.com"})
        assert resp_a.headers.get("access-control-allow-origin") == "https://a.example.com"
        assert resp_b.headers.get("access-control-allow-origin") == "https://b.example.com"
        assert "access-control-allow-origin" not in resp_other.headers
    finally:
        monkeypatch.undo()
        _reload_main()


@pytest.mark.asyncio
async def test_cors_origins_unset_uses_default_list(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    try:
        reloaded = _reload_main()
        async with AsyncClient(transport=ASGITransport(app=reloaded.app), base_url="http://test") as ac:
            allowed = await ac.get("/", headers={"Origin": "http://localhost:3000"})
            blocked = await ac.get("/", headers={"Origin": "https://totally-unlisted.example.com"})
        assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert "access-control-allow-origin" not in blocked.headers
    finally:
        monkeypatch.undo()
        _reload_main()


# ---------------------------------------------------------------------------
# Sentry initialization (only when SENTRY_DSN is set). sentry_sdk.init is
# fully mocked out so this never touches the network, even though it's
# invoked for real by module-level code during reload.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sentry_disabled_in_development_even_with_dsn(monkeypatch):
    import sentry_sdk

    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fake.ingest.sentry.io/123")
    monkeypatch.setenv("ENV", "development")
    try:
        _reload_main()
        mock_init.assert_not_called()
    finally:
        monkeypatch.undo()
        _reload_main()


@pytest.mark.asyncio
async def test_sentry_initialized_in_production_when_dsn_set(monkeypatch):
    import sentry_sdk

    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fake.ingest.sentry.io/123")
    monkeypatch.setenv("ENV", "production")
    try:
        _reload_main()
        mock_init.assert_called_once()
        _, kwargs = mock_init.call_args
        assert kwargs["dsn"] == "https://fakekey@fake.ingest.sentry.io/123"
        assert kwargs["environment"] == "production"
    finally:
        monkeypatch.undo()
        _reload_main()


@pytest.mark.asyncio
async def test_sentry_enforced_in_production_raises_without_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("ENV", "production")
    try:
        with pytest.raises(RuntimeError, match="SENTRY_DSN environment variable is strictly required in production"):
            _reload_main()
    finally:
        monkeypatch.undo()
        _reload_main()


# ---------------------------------------------------------------------------
# IS_PROD gating of /docs, /redoc, /openapi.json
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_docs_reachable_when_not_prod():
    # conftest's baseline env sets ENV=test (not production), so the
    # module-level `app` imported at the top of this file already has docs
    # enabled -- no reload needed for this half of the behavior.
    assert main.IS_PROD is False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        docs_resp = await ac.get("/docs")
        openapi_resp = await ac.get("/openapi.json")
    assert docs_resp.status_code == 200
    assert openapi_resp.status_code == 200


@pytest.mark.asyncio
async def test_docs_hidden_when_env_is_production(monkeypatch):
    import sentry_sdk
    monkeypatch.setattr(sentry_sdk, "init", MagicMock())
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fake.ingest.sentry.io/123")
    monkeypatch.setenv("ENV", "production")
    try:
        reloaded = _reload_main()
        assert reloaded.IS_PROD is True
        async with AsyncClient(transport=ASGITransport(app=reloaded.app), base_url="http://test") as ac:
            docs_resp = await ac.get("/docs")
            redoc_resp = await ac.get("/redoc")
            openapi_resp = await ac.get("/openapi.json")
        assert docs_resp.status_code == 404
        assert redoc_resp.status_code == 404
        assert openapi_resp.status_code == 404
    finally:
        monkeypatch.undo()
        _reload_main()


@pytest.mark.asyncio
async def test_docs_hidden_when_env_is_prod_shorthand(monkeypatch):
    import sentry_sdk
    # IS_PROD accepts "prod" as well as "production" (case-insensitively).
    monkeypatch.setattr(sentry_sdk, "init", MagicMock())
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fake.ingest.sentry.io/123")
    monkeypatch.setenv("ENV", "PROD")
    try:
        reloaded = _reload_main()
        assert reloaded.IS_PROD is True
        async with AsyncClient(transport=ASGITransport(app=reloaded.app), base_url="http://test") as ac:
            docs_resp = await ac.get("/docs")
        assert docs_resp.status_code == 404
    finally:
        monkeypatch.undo()
        _reload_main()


# ---------------------------------------------------------------------------
# lifespan() background task gating
#
# Unlike CORS_ORIGINS/IS_PROD, lifespan() reads os.environ at *call* time
# (inside the async function body), so these tests monkeypatch env vars and
# invoke main.lifespan(...) directly -- no importlib.reload needed.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_no_background_task_when_cleanup_disabled():
    # conftest's baseline env already has DISABLE_PAYMENT_CLEANUP=1, so the
    # gating condition should be False and no task should be scheduled.
    assert os.environ.get("DISABLE_PAYMENT_CLEANUP") == "1"
    mock_create_task = MagicMock()
    orig_create_task = main.asyncio.create_task
    main.asyncio.create_task = mock_create_task
    try:
        async with main.lifespan(main.app):
            pass
    finally:
        main.asyncio.create_task = orig_create_task
    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_no_background_task_on_vercel_even_if_cleanup_enabled(monkeypatch):
    # conftest's baseline env sets VERCEL=1. Even if cleanup is *not*
    # disabled, the serverless (VERCEL) check alone should suppress the task.
    monkeypatch.delenv("DISABLE_PAYMENT_CLEANUP", raising=False)
    assert os.environ.get("VERCEL") == "1"
    mock_create_task = MagicMock()
    orig_create_task = main.asyncio.create_task
    main.asyncio.create_task = mock_create_task
    try:
        async with main.lifespan(main.app):
            pass
    finally:
        main.asyncio.create_task = orig_create_task
    mock_create_task.assert_not_called()


@pytest.mark.asyncio
def _started_worker_names(mock_create_task) -> set[str]:
    """The coroutine functions the lifespan actually scheduled."""
    return {call.args[0].__qualname__ for call in mock_create_task.call_args_list}


@pytest.mark.asyncio
async def test_lifespan_creates_background_tasks_when_enabled(monkeypatch):
    # Every gate must be open: not on Vercel, and neither worker disabled.
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DISABLE_PAYMENT_CLEANUP", raising=False)
    monkeypatch.delenv("DISABLE_UNREAD_DIGEST", raising=False)

    real_create_task = asyncio.create_task
    mock_create_task = MagicMock(side_effect=real_create_task)
    orig_create_task = main.asyncio.create_task
    main.asyncio.create_task = mock_create_task
    try:
        async with main.lifespan(main.app):
            pass
    finally:
        main.asyncio.create_task = orig_create_task

    # SPEC-052 added the digest sweeper alongside the payment cleanup worker.
    assert _started_worker_names(mock_create_task) == {
        "_payment_cleanup_loop", "_unread_digest_loop"
    }


@pytest.mark.asyncio
async def test_lifespan_can_disable_the_digest_worker_alone(monkeypatch):
    """SPEC-052: DISABLE_UNREAD_DIGEST opts out of digests without also
    stopping payment cleanup — they are separate concerns on separate switches."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DISABLE_PAYMENT_CLEANUP", raising=False)
    monkeypatch.setenv("DISABLE_UNREAD_DIGEST", "1")

    real_create_task = asyncio.create_task
    mock_create_task = MagicMock(side_effect=real_create_task)
    orig_create_task = main.asyncio.create_task
    main.asyncio.create_task = mock_create_task
    try:
        async with main.lifespan(main.app):
            pass
    finally:
        main.asyncio.create_task = orig_create_task

    assert _started_worker_names(mock_create_task) == {"_payment_cleanup_loop"}
