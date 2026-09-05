from unittest.mock import MagicMock

import pytest
from postgrest._sync.request_builder import SyncQueryRequestBuilder
from postgrest.exceptions import APIError

import connector


def test_resilient_execute_retries_on_jwt_future(monkeypatch):
    call_count = 0

    def mock_orig(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError({"message": "JWT issued at future", "code": "PGRST301"})
        return "success"

    monkeypatch.setattr(connector, "_orig_postgrest_execute", mock_orig)
    monkeypatch.setattr(connector.time, "sleep", lambda _s: None)

    builder = MagicMock(spec=SyncQueryRequestBuilder)
    res = connector._resilient_postgrest_execute(builder)

    assert res == "success"
    assert call_count == 2


def test_resilient_execute_raises_if_not_jwt_future(monkeypatch):
    call_count = 0

    def mock_orig(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise APIError({"message": "relation does not exist", "code": "42P01"})

    monkeypatch.setattr(connector, "_orig_postgrest_execute", mock_orig)

    builder = MagicMock(spec=SyncQueryRequestBuilder)
    with pytest.raises(APIError) as exc_info:
        connector._resilient_postgrest_execute(builder)

    assert "relation does not exist" in str(exc_info.value)
    assert call_count == 1


def test_resilient_execute_raises_if_retry_fails(monkeypatch):
    call_count = 0

    def mock_orig(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise APIError({"message": "JWT issued at future", "code": "PGRST301"})

    monkeypatch.setattr(connector, "_orig_postgrest_execute", mock_orig)
    monkeypatch.setattr(connector.time, "sleep", lambda _s: None)

    builder = MagicMock(spec=SyncQueryRequestBuilder)
    with pytest.raises(APIError) as exc_info:
        connector._resilient_postgrest_execute(builder)

    assert "JWT issued at future" in str(exc_info.value)
    assert call_count == 2
