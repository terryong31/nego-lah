from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agent.tools.image_analyzer import image_analyzer
from auth_middleware import verify_user_token
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
        with patch("routes.user.admin_supabase") as mock_supabase:
            mock_supabase.auth.admin.get_user_by_id.return_value = mock_response

            res = client.put(
                f"/user/{USER_ID}/language",
                headers={"Authorization": "Bearer valid_token"},
                json={"language": "ms"}
            )

            assert res.status_code == 200
            data = res.json()
            assert data["preferred_language"] == "ms"
            assert data["message"] == "Language updated"

            mock_supabase.auth.admin.update_user_by_id.assert_called_once_with(
                USER_ID,
                {"user_metadata": {"display_name": "Test User", "preferred_language": "ms"}}
            )
    finally:
        app.dependency_overrides.pop(verify_user_token, None)


def test_update_language_unsupported_locale():
    """Unsupported language codes are rejected with 400 Bad Request."""
    app.dependency_overrides[verify_user_token] = lambda: USER_ID
    try:
        res = client.put(
            f"/user/{USER_ID}/language",
            headers={"Authorization": "Bearer valid_token"},
            json={"language": "fr"}
        )
        assert res.status_code == 400
        assert "Unsupported language" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_user_token, None)


def test_update_language_unauthorized():
    """Missing or invalid token returns 401."""
    res = client.put(
        f"/user/{USER_ID}/language",
        json={"language": "zh"}
    )
    assert res.status_code == 401


def test_image_analyzer_multilingual_prompts():
    """Image analyzer build prompts include language directives for ms, zh, en."""
    prompt_en = image_analyzer._build_prompt("identify", language="en")
    assert "English" in prompt_en

    prompt_ms = image_analyzer._build_prompt("identify", language="ms")
    assert "Bahasa Melayu" in prompt_ms

    prompt_zh = image_analyzer._build_prompt("identify", language="zh")
    assert "Simplified Chinese" in prompt_zh or "简体中文" in prompt_zh
