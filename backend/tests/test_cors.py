from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_cors_preflight_allows_cloudflare_pages_domain():
    response = client.options(
        "/items",
        headers={
            "Origin": "https://nego-lah.pages.dev",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://nego-lah.pages.dev"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_allows_branch_preview_pages_domain():
    response = client.options(
        "/items",
        headers={
            "Origin": "https://preview-123.nego-lah.pages.dev",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://preview-123.nego-lah.pages.dev"


def test_cors_rejects_unauthorized_domain():
    response = client.options(
        "/items",
        headers={
            "Origin": "https://malicious-site.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_rejects_unauthorized_pages_dev_domain():
    response = client.options(
        "/items",
        headers={
            "Origin": "https://attacker.pages.dev",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_production_mode_rejects_pages_dev(monkeypatch):
    import importlib

    import main

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SENTRY_DSN", "https://mock@sentry.io/123")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    try:
        reloaded = importlib.reload(main)
        prod_client = TestClient(reloaded.app)

        # In production, canonical domain is allowed
        allowed = prod_client.options(
            "/items",
            headers={
                "Origin": "https://negolah.my",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers.get("access-control-allow-origin") == "https://negolah.my"

        # In production, pages.dev domains are strictly rejected
        blocked = prod_client.options(
            "/items",
            headers={
                "Origin": "https://nego-lah.pages.dev",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert blocked.headers.get("access-control-allow-origin") is None
    finally:
        monkeypatch.undo()
        importlib.reload(main)


def test_defense_middleware_413_still_carries_cors_headers():
    """
    Regression: RequestDefenseMiddleware short-circuits oversized uploads with
    a 413 *before* calling call_next. If CORSMiddleware is mounted inward of
    it, that 413 never gets Access-Control-* headers and the browser reports
    a CORS failure instead of "Payload too large" (see SPEC-042 — this is why
    sellers couldn't upload items with photos attached).
    """
    oversized = 16 * 1024 * 1024  # over the 15MB upload cap that /admin/items gets
    response = client.post(
        "/admin/items",
        headers={
            "Origin": "https://negolah.my",
            "Content-Length": str(oversized),
        },
        content=b"x" * 100,
    )
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "https://negolah.my"


def test_defense_middleware_413_omits_cors_headers_for_disallowed_origin():
    oversized = 16 * 1024 * 1024
    response = client.post(
        "/admin/items",
        headers={
            "Origin": "https://malicious-site.com",
            "Content-Length": str(oversized),
        },
        content=b"x" * 100,
    )
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") is None
