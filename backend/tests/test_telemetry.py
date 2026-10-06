from unittest.mock import MagicMock

import pytest
import sentry_sdk

from core.telemetry import init_sentry


def test_init_sentry_disabled_in_development(monkeypatch):
    """In development mode (is_prod=False), Sentry SDK must never be initialized even if DSN is set."""
    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fake@o123.ingest.sentry.io/456")

    init_sentry(is_prod=False)

    mock_init.assert_not_called()


def test_init_sentry_enforced_in_production_success(monkeypatch):
    """In production mode (is_prod=True), Sentry must be initialized with production settings."""
    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fake@o123.ingest.sentry.io/456")

    init_sentry(is_prod=True)

    mock_init.assert_called_once()
    _, kwargs = mock_init.call_args
    assert kwargs["dsn"] == "https://fake@o123.ingest.sentry.io/456"
    assert kwargs["environment"] == "production"
    assert kwargs["traces_sample_rate"] == 0.2
    assert kwargs["profile_session_sample_rate"] == 0.1


def test_init_sentry_enforced_in_production_missing_dsn_raises(monkeypatch):
    """In production mode, missing SENTRY_DSN must raise a RuntimeError."""
    monkeypatch.setenv("SENTRY_DSN", "")

    with pytest.raises(RuntimeError, match="SENTRY_DSN environment variable is strictly required in production"):
        init_sentry(is_prod=True)


def test_sentry_events_never_carry_session_cookies(monkeypatch):
    """Audit SEC-1: `send_default_pii` attaches cookies, and none of ours are on
    Sentry's default denylist — so a live admin session reached Sentry."""
    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fake@o123.ingest.sentry.io/456")

    init_sentry(is_prod=True)

    before_send = mock_init.call_args.kwargs["before_send"]
    event = {
        "request": {
            "cookies": {"nl_sid": "SID", "admin_sid": "ADMIN", "nl_csrf": "C"},
            "headers": {"Cookie": "nl_sid=SID", "Authorization": "Bearer T", "X-CSRF-Token": "C", "Accept": "*/*"},
        }
    }
    scrubbed = before_send(event, {})

    assert "cookies" not in scrubbed["request"]
    headers = scrubbed["request"]["headers"]
    assert headers["Cookie"] == headers["Authorization"] == headers["X-CSRF-Token"] == "[Filtered]"
    assert headers["Accept"] == "*/*"
    assert mock_init.call_args.kwargs["before_send_transaction"] is before_send
