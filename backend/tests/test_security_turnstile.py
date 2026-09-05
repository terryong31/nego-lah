from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core.security import verify_turnstile


@pytest.mark.asyncio
async def test_verify_turnstile_bypassed_in_development(monkeypatch):
    """In development mode (not production), verification is completely bypassed even if secret is set."""
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "prod-like-secret")

    # Bypasses when token is missing
    result = await verify_turnstile(x_turnstile_token=None)
    assert result is True

    # Bypasses when dummy token is provided
    result_dummy = await verify_turnstile(x_turnstile_token="dummy-token")
    assert result_dummy is True


@pytest.mark.asyncio
async def test_verify_turnstile_prod_missing_secret_raises_500(monkeypatch):
    """In production mode, if TURNSTILE_SECRET_KEY is unset/empty, raise 500 configuration error."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    monkeypatch.setenv("TURNSTILE_SECRET", "")

    with pytest.raises(HTTPException) as exc_info:
        await verify_turnstile(x_turnstile_token="some-token")
    assert exc_info.value.status_code == 500
    assert "not configured in production" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_verify_turnstile_prod_missing_token_raises_400(monkeypatch):
    """In production mode, if token is missing or empty, raise 400."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret-key")

    with pytest.raises(HTTPException) as exc_info:
        await verify_turnstile(x_turnstile_token=None)
    assert exc_info.value.status_code == 400
    assert "required" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_verify_turnstile_prod_rejects_dummy_tokens(monkeypatch):
    """In production mode, dummy/test tokens must be rejected with 403."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret-key")

    for dummy in ("dummy-token", "test-token", "XXXX.DUMMY.12345"):
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile(x_turnstile_token=dummy)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_turnstile_prod_rejects_test_secret(monkeypatch):
    """In production mode, using Cloudflare's dummy test secret must be rejected."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "1x0000000000000000000000000000000AA")

    with pytest.raises(HTTPException) as exc_info:
        await verify_turnstile(x_turnstile_token="real-token")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_turnstile_prod_success(monkeypatch):
    """In production mode, valid token verified by Cloudflare siteverify returns True."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret-key")

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"success": True}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await verify_turnstile(x_turnstile_token="valid-production-token")
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["data"]["secret"] == "real-prod-secret-key"
        assert kwargs["data"]["response"] == "valid-production-token"


@pytest.mark.asyncio
async def test_verify_turnstile_prod_failure_raises_403(monkeypatch):
    """In production mode, failed verification by Cloudflare siteverify raises 403."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret-key")

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(HTTPException) as exc_info:
            await verify_turnstile(x_turnstile_token="rejected-token")
        assert exc_info.value.status_code == 403
        assert "failed" in exc_info.value.detail.lower()
