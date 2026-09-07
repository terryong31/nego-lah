"""
Unit tests for FastAPI defense middleware:
- SecurityHeadersMiddleware (OWASP security headers, HSTS in production, CSP)
- RequestDefenseMiddleware (payload size enforcement, null-byte injection detection)
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.defense_middleware import RequestDefenseMiddleware, SecurityHeadersMiddleware


@pytest.fixture
def defense_test_app(monkeypatch):
    """Creates a standalone FastAPI test app wrapped with defense middleware."""
    app = FastAPI()

    # Mount middleware (inner to outer)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RequestDefenseMiddleware,
        max_content_length=1024 * 1024,  # 1MB limit for testing
        upload_path_prefix="/admin/analyze-image",
        max_upload_content_length=2 * 1024 * 1024,  # 2MB upload limit
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/items")
    async def create_item(request: Request):
        body = await request.body()
        return {"received": len(body)}

    @app.post("/admin/analyze-image")
    async def analyze_image(request: Request):
        body = await request.body()
        return {"received": len(body)}

    return app


def test_security_headers_present_on_response(defense_test_app):
    client = TestClient(defense_test_app)
    res = client.get("/health")
    assert res.status_code == 200
    headers = res.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "0"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "default-src 'none'" in headers.get("Content-Security-Policy", "")
    assert "camera=()" in headers.get("Permissions-Policy", "")
    assert headers.get("X-Permitted-Cross-Domain-Policies") == "none"


def test_hsts_header_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ping": "pong"}

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    assert "Strict-Transport-Security" in res.headers
    assert "max-age=31536000" in res.headers["Strict-Transport-Security"]


def test_hsts_header_omitted_in_development(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ping": "pong"}

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    assert "Strict-Transport-Security" not in res.headers


def test_request_payload_within_limit_succeeds(defense_test_app):
    client = TestClient(defense_test_app)
    payload = b"a" * 1024  # 1 KB
    res = client.post("/items", content=payload)
    assert res.status_code == 200
    assert res.json()["received"] == 1024


def test_request_payload_exceeding_limit_rejected_with_413(defense_test_app):
    client = TestClient(defense_test_app)
    # Header claims 1.5MB (> 1MB standard limit)
    oversized = 1024 * 1024 + 500
    res = client.post(
        "/items",
        headers={"Content-Length": str(oversized)},
        content=b"x" * 100
    )
    assert res.status_code == 413
    assert "Payload too large" in res.json()["detail"]


def test_upload_path_allows_larger_limit(defense_test_app):
    client = TestClient(defense_test_app)
    # 1.5MB is allowed on upload route (limit is 2MB)
    size = int(1.5 * 1024 * 1024)
    res = client.post(
        "/admin/analyze-image",
        headers={"Content-Length": str(size)},
        content=b"x" * 100
    )
    assert res.status_code == 200

    # But 2.5MB is rejected
    too_large = int(2.5 * 1024 * 1024)
    res_too_large = client.post(
        "/admin/analyze-image",
        headers={"Content-Length": str(too_large)},
        content=b"x" * 100
    )
    assert res_too_large.status_code == 413


def test_null_byte_in_url_rejected_with_400(defense_test_app):
    client = TestClient(defense_test_app)
    # URL with null byte injection
    res = client.get("/health%00evil")
    assert res.status_code == 400
    assert "Invalid request path" in res.json()["detail"]


def test_upload_path_prefix_accepts_tuple_of_prefixes():
    app = FastAPI()
    app.add_middleware(
        RequestDefenseMiddleware,
        max_content_length=1024 * 1024,
        upload_path_prefix=("/admin/analyze-image", "/admin/items"),
        max_upload_content_length=2 * 1024 * 1024,
    )

    @app.post("/admin/items")
    async def create_item(request: Request):
        body = await request.body()
        return {"received": len(body)}

    @app.post("/admin/other")
    async def other(request: Request):
        body = await request.body()
        return {"received": len(body)}

    client = TestClient(app)

    # 1.5MB allowed on /admin/items (2MB upload limit applies to both prefixes)
    size = int(1.5 * 1024 * 1024)
    res = client.post(
        "/admin/items",
        headers={"Content-Length": str(size)},
        content=b"x" * 100,
    )
    assert res.status_code == 200

    # A path not in the tuple still falls back to the default 1MB limit
    res_default_limit = client.post(
        "/admin/other",
        headers={"Content-Length": str(size)},
        content=b"x" * 100,
    )
    assert res_default_limit.status_code == 413


def test_admin_items_upload_gets_larger_default_limit():
    """POST /admin/items must get the 15MB upload ceiling by default, not the 10MB one."""
    app = FastAPI()
    app.add_middleware(RequestDefenseMiddleware)

    @app.post("/admin/items")
    async def create_item(request: Request):
        body = await request.body()
        return {"received": len(body)}

    client = TestClient(app)

    over_default_under_upload = 12 * 1024 * 1024  # > 10MB default, < 15MB upload ceiling
    res = client.post(
        "/admin/items",
        headers={"Content-Length": str(over_default_under_upload)},
        content=b"x" * 100,
    )
    assert res.status_code == 200
