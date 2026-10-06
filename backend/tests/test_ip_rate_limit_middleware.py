import asyncio
from collections.abc import AsyncGenerator

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

import core.limiter as limiter_module
from core.cache import redis_client
from core.rate_limit_middleware import IPRateLimitMiddleware


@pytest.fixture(autouse=True)
def clean_redis():
    # Clean up rate keys between tests
    for k in list(redis_client.keys("rate:ip:*")):
        redis_client.delete(k)
    yield
    for k in list(redis_client.keys("rate:ip:*")):
        redis_client.delete(k)


def create_test_app():
    app = FastAPI()

    # Track how many times auth was invoked
    auth_calls = {"count": 0}

    async def dummy_auth(request: Request):
        auth_calls["count"] += 1
        auth_header = request.headers.get("Authorization", "")
        if auth_header != "Bearer valid-token":
            raise HTTPException(status_code=401, detail="Invalid token")
        return "user-123"

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/items")
    def catalog():
        return {"items": []}

    @app.post("/payment/checkout")
    def checkout(user_id: str = Depends(dummy_auth)):
        return {"status": "success", "user": user_id}

    @app.get("/stream")
    async def sse_stream():
        async def event_gen() -> AsyncGenerator[str, None]:
            yield "data: chunk1\n\n"
            await asyncio.sleep(0.01)
            yield "data: chunk2\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    app.add_middleware(IPRateLimitMiddleware)
    return app, auth_calls


@pytest.mark.asyncio
async def test_health_check_exempted_from_rate_limits(monkeypatch):
    monkeypatch.setattr(limiter_module, "DEFAULT_LIMIT", "0/minute")
    app, _ = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(limiter_module, "CATALOG_LIMIT", "2/minute")
    app, _ = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.get("/items")
        assert r1.status_code == 200

        r2 = await ac.get("/items")
        assert r2.status_code == 200

        r3 = await ac.get("/items")
        assert r3.status_code == 429
        assert r3.json()["detail"] == "Rate limit exceeded. Too many requests."
        assert "Retry-After" in r3.headers


@pytest.mark.asyncio
async def test_pre_routing_rate_limiting_runs_before_auth(monkeypatch):
    """SPEC-077 / TODO 64: 3 forged tokens past a 2/min limit -> 2x401 then 429.
    On the 3rd request, auth is NEVER invoked."""
    monkeypatch.setattr(limiter_module, "CHECKOUT_LIMIT", "2/minute")
    app, auth_calls = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": "Bearer forged-token"}

        # Request 1: Auth runs -> 401
        r1 = await ac.post("/payment/checkout", headers=headers)
        assert r1.status_code == 401

        # Request 2: Auth runs -> 401
        r2 = await ac.post("/payment/checkout", headers=headers)
        assert r2.status_code == 401

        # Both incremented the rate limiter
        assert auth_calls["count"] == 2

        # Request 3: Exceeds limit! Must return 429 BEFORE auth runs!
        r3 = await ac.post("/payment/checkout", headers=headers)
        assert r3.status_code == 429
        assert r3.json()["detail"] == "Rate limit exceeded. Too many requests."

        # Auth count must still be 2 -- auth was bypassed by the 429!
        assert auth_calls["count"] == 2


@pytest.mark.asyncio
async def test_cf_connecting_ip_keys_the_rate_limit(monkeypatch):
    monkeypatch.setattr(limiter_module, "CATALOG_LIMIT", "1/minute")
    app, _ = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # IP 1 uses its budget
        r1 = await ac.get("/items", headers={"CF-Connecting-IP": "198.51.100.1"})
        assert r1.status_code == 200

        # IP 1 is blocked
        r1_blocked = await ac.get("/items", headers={"CF-Connecting-IP": "198.51.100.1"})
        assert r1_blocked.status_code == 429

        # IP 2 has fresh budget
        r2 = await ac.get("/items", headers={"CF-Connecting-IP": "198.51.100.2"})
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_streaming_response_is_not_buffered():
    app, _ = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        chunks = []
        async with ac.stream("GET", "/stream") as res:
            assert res.status_code == 200
            async for chunk in res.aiter_text():
                chunks.append(chunk)

        content = "".join(chunks)
        assert "data: chunk1" in content
        assert "data: chunk2" in content


@pytest.mark.asyncio
async def test_a_redis_failure_fails_open_rather_than_500ing_every_route(monkeypatch):
    """Audit REL-1: the limiter had no `try`, so a Redis outage took the storefront down."""
    import core.rate_limit_middleware as middleware

    def broken(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(middleware, "check_ip_rate_limit", broken)
    app, _ = create_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/items")
        assert res.status_code == 200
