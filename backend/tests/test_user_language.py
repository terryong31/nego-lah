from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from domains.identity.auth_middleware import verify_user_token
from domains.negotiation.tools.image_analyzer import image_analyzer
from main import app

client = TestClient(app)

USER_ID = "00000000-0000-0000-0000-000000000001"


def test_update_language_success():
    """Authenticated user can update their preferred language to a supported locale."""
    mock_user = MagicMock()
    mock_user.user_metadata = {"display_name": "Test User"}
    mock_response = MagicMock(user=mock_user)

    app.dependency_overrides[verify_user_token] = lambda: USER_ID
    try:
        with patch("domains.identity.routes.admin_supabase") as mock_supabase:
            mock_supabase.auth.admin.get_user_by_id.return_value = mock_response

            res = client.put(
                f"/user/{USER_ID}/language", headers={"Authorization": "Bearer valid_token"}, json={"language": "ms"}
            )

            assert res.status_code == 200
            data = res.json()
            assert data["preferred_language"] == "ms"
            assert data["message"] == "Language updated"

            mock_supabase.auth.admin.update_user_by_id.assert_called_once_with(
                USER_ID, {"user_metadata": {"display_name": "Test User", "preferred_language": "ms"}}
            )
    finally:
        app.dependency_overrides.pop(verify_user_token, None)


def test_update_language_unsupported_locale():
    """Unsupported language codes are rejected with 400 Bad Request."""
    app.dependency_overrides[verify_user_token] = lambda: USER_ID
    try:
        res = client.put(
            f"/user/{USER_ID}/language", headers={"Authorization": "Bearer valid_token"}, json={"language": "fr"}
        )
        assert res.status_code == 400
        assert "Unsupported language" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_user_token, None)


def test_update_language_unauthorized():
    """Missing or invalid token returns 401."""
    res = client.put(f"/user/{USER_ID}/language", json={"language": "zh"})
    assert res.status_code == 401


def test_image_analyzer_multilingual_prompts():
    """Image analyzer build prompts include language directives for ms, zh, en."""
    prompt_en = image_analyzer._build_prompt("identify", language="en")
    assert "English" in prompt_en

    prompt_ms = image_analyzer._build_prompt("identify", language="ms")
    assert "Bahasa Melayu" in prompt_ms

    prompt_zh = image_analyzer._build_prompt("identify", language="zh")
    assert "Simplified Chinese" in prompt_zh or "简体中文" in prompt_zh


def test_get_user_preferred_language_none():
    """None or empty user_id defaults safely to 'en'."""
    from domains.identity.routes import get_user_preferred_language

    assert get_user_preferred_language(None) == "en"
    assert get_user_preferred_language("") == "en"


def test_get_user_preferred_language_redis_cache():
    """Hits Redis cache directly when key exists."""
    from domains.identity.routes import get_user_preferred_language

    mock_redis = MagicMock()
    mock_redis.get.return_value = b"ms"

    with patch("core.cache.redis_client", mock_redis):
        assert get_user_preferred_language("user-123") == "ms"
        mock_redis.get.assert_called_once_with("user:user-123:lang")


def test_get_user_preferred_language_supabase_fallback():
    """Fetches from Supabase user_metadata on Redis miss, then sets cache."""
    from domains.identity.routes import get_user_preferred_language

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    mock_user = MagicMock()
    mock_user.user_metadata = {"preferred_language": "zh"}
    mock_res = MagicMock(user=mock_user)

    with patch("core.cache.redis_client", mock_redis), patch("domains.identity.routes.admin_supabase") as mock_supabase:
        mock_supabase.auth.admin.get_user_by_id.return_value = mock_res
        assert get_user_preferred_language("user-456") == "zh"
        mock_redis.set.assert_called_once_with("user:user-456:lang", "zh", ex=86400)


def test_get_user_preferred_language_fallback_on_error():
    """Defaults to 'en' when lookup encounters unexpected exceptions."""
    from domains.identity.routes import get_user_preferred_language

    mock_redis = MagicMock()
    mock_redis.get.side_effect = RuntimeError("Redis down")

    with patch("core.cache.redis_client", mock_redis), patch("domains.identity.routes.admin_supabase") as mock_supabase:
        mock_supabase.auth.admin.get_user_by_id.side_effect = RuntimeError("Supabase down")
        assert get_user_preferred_language("user-789") == "en"


def test_agent_context_language():
    """Context tracks active language isolated per execution."""
    from domains.negotiation.context import get_user_language, set_context

    set_context(user_id="u1", item_id="item-1", language="ms")
    assert get_user_language() == "ms"

    set_context(user_id="u2", item_id="item-2", language="zh")
    assert get_user_language() == "zh"

    set_context(user_id="u3", item_id="item-3", language=None)
    assert get_user_language() == "en"


def test_agent_build_messages_language_directives(monkeypatch):
    """_build_messages injects explicit directives for ms, zh, en when specified."""
    from domains.negotiation import bot

    monkeypatch.setattr(bot.conversation_memory, "get_history", lambda uid, limit=10, include_tool_calls=False: [])

    # Malay
    msgs_ms = bot._build_messages("u1", "boleh kurang lagi?", language="ms")
    assert any("Bahasa Melayu" in str(m.content) for m in msgs_ms)

    # Chinese
    msgs_zh = bot._build_messages("u1", "可以便宜点吗？", language="zh")
    assert any("Simplified Chinese" in str(m.content) or "简体中文" in str(m.content) for m in msgs_zh)

    # English
    msgs_en = bot._build_messages("u1", "can discount?", language="en")
    assert any("Malaysian English" in str(m.content) for m in msgs_en)


def test_agent_build_messages_with_context_language(monkeypatch):
    """_build_messages respects context language when language parameter is omitted."""
    from domains.negotiation import bot
    from domains.negotiation.context import set_context

    monkeypatch.setattr(bot.conversation_memory, "get_history", lambda uid, limit=10, include_tool_calls=False: [])

    set_context(user_id="u1", language="ms")
    msgs = bot._build_messages("u1", "harga berapa?")
    assert any("Bahasa Melayu" in str(m.content) for m in msgs)
    set_context(user_id="u1", language="en")
