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
