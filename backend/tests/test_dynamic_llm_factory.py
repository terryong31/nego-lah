from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.llm_factory import (
    LOCAL_LLM_PROBE_KEY,
    PROBE_CACHE_TTL,
    aget_chat_model,
    get_chat_model,
    is_local_llm_available,
    is_local_llm_available_sync,
)


@pytest.fixture(autouse=True)
def clean_redis_cache():
    """Ensure probe cache key is cleared before each test."""
    from cache import redis_client
    try:
        redis_client.delete(LOCAL_LLM_PROBE_KEY)
    except Exception:  # noqa: S110
        pass
    yield
    try:
        redis_client.delete(LOCAL_LLM_PROBE_KEY)
    except Exception:  # noqa: S110
        pass


@pytest.mark.asyncio
async def test_is_local_llm_available_success():
    """Test successful async probe caches status and returns True."""
    from cache import redis_client

    mock_response = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await is_local_llm_available()
        assert result is True
        assert mock_get.called

        cached = redis_client.get(LOCAL_LLM_PROBE_KEY)
        assert cached is not None
        val = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        assert val == "1"


def test_is_local_llm_available_sync_success():
    """Test successful sync probe caches status and returns True."""
    from cache import redis_client

    mock_response = MagicMock(status_code=200)
    with patch("httpx.Client.get", return_value=mock_response) as mock_get:
        result = is_local_llm_available_sync()
        assert result is True
        assert mock_get.called

        cached = redis_client.get(LOCAL_LLM_PROBE_KEY)
        assert cached is not None
        val = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        assert val == "1"


@pytest.mark.asyncio
async def test_is_local_llm_available_uses_cache():
    """Test that existing cache avoids HTTP request."""
    from cache import redis_client

    redis_client.set(LOCAL_LLM_PROBE_KEY, "1", ex=PROBE_CACHE_TTL)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        result = await is_local_llm_available()
        assert result is True
        mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_is_local_llm_available_failure_timeout():
    """Test probe timeout returns False and caches 0."""
    from cache import redis_client

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Tunnel down")
        result = await is_local_llm_available()
        assert result is False

        cached = redis_client.get(LOCAL_LLM_PROBE_KEY)
        assert cached is not None
        val = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        assert val == "0"


def test_get_chat_model_returns_local_when_healthy(monkeypatch):
    """When local LLM is available, get_chat_model returns ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")

    with patch("agent.llm_factory.is_local_llm_available_sync", return_value=True):
        model = get_chat_model(temperature=0.5)

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "mlx-community/Qwen3.6-35B-A3B-4bit"
        assert model.temperature == 0.5


def test_get_chat_model_falls_back_to_gemini_when_unhealthy(monkeypatch):
    """When local LLM is unavailable, get_chat_model falls back to ChatGoogleGenerativeAI."""
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")

    with patch("agent.llm_factory.is_local_llm_available_sync", return_value=False):
        model = get_chat_model(temperature=0.3)

        assert isinstance(model, ChatGoogleGenerativeAI)
        assert model.model == "gemini-3.8-flash"
        assert model.temperature == 0.3


@pytest.mark.asyncio
async def test_aget_chat_model_returns_local_when_healthy(monkeypatch):
    """When local LLM is available, aget_chat_model returns ChatOpenAI."""
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")

    with patch("agent.llm_factory.is_local_llm_available", new_callable=AsyncMock) as mock_avail:
        mock_avail.return_value = True
        model = await aget_chat_model(temperature=0.5)

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "mlx-community/Qwen3.6-35B-A3B-4bit"
        assert model.temperature == 0.5


def test_get_chat_model_forced_gemini(monkeypatch):
    """Forcing gemini provider skips local probe and returns ChatGoogleGenerativeAI."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    with patch("agent.llm_factory.is_local_llm_available_sync") as mock_avail:
        model = get_chat_model(force_provider="gemini")
        mock_avail.assert_not_called()
        assert isinstance(model, ChatGoogleGenerativeAI)


def test_get_chat_model_missing_gemini_key_raises(monkeypatch):
    """When Gemini is needed but GEMINI_API_KEY is missing, RuntimeError is raised."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    with pytest.raises(RuntimeError, match="Missing GEMINI_API_KEY"):
        get_chat_model(force_provider="gemini")
