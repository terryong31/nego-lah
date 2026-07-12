"""Tests for routes/webhooks.py — POST /webhooks/resend.

Mocking approach (see conftest.py docstring for general rationale):
  - `svix.webhooks.Webhook` is imported by name into routes.webhooks
    (`from svix.webhooks import Webhook`), so we monkeypatch
    `routes.webhooks.Webhook` with a fake class whose `.verify(...)` either
    returns a canned event dict or raises to exercise the error branches.
  - `httpx` is imported as a module (`import httpx`) and used as
    `httpx.AsyncClient()`, so we monkeypatch
    `routes.webhooks.httpx.AsyncClient` with a MagicMock factory that
    produces an async-context-manager whose `.get`/`.post` are AsyncMocks we
    control per test.
"""

import email.message
from email import policy as email_policy
from unittest.mock import AsyncMock, MagicMock

import httpx
from svix.webhooks import WebhookVerificationError

import routes.webhooks as webhooks_module

RESEND_WEBHOOK_URL = "/webhooks/resend"


def _webhook_headers():
    return {
        "svix-id": "msg_123",
        "svix-timestamp": "1700000000",
        "svix-signature": "v1,fakesignature==",
    }


def _install_fake_webhook(monkeypatch, *, return_value=None, side_effect=None):
    """Patch routes.webhooks.Webhook so Webhook(secret).verify(...) is controlled."""

    class FakeWebhook:
        def __init__(self, secret):
            self.secret = secret

        def verify(self, payload, headers):
            if side_effect is not None:
                raise side_effect
            return return_value

    monkeypatch.setattr(webhooks_module, "Webhook", FakeWebhook)


def _install_fake_async_client(monkeypatch, *, get_effect=None, post_effect=None):
    """Patch routes.webhooks.httpx.AsyncClient.

    `get_effect` / `post_effect` may each be:
      - a single value/exception (applied to every call), or
      - a list of values/exceptions (applied in order, one per call — useful
        since the happy path calls client.get() up to twice).
    Any element that is an Exception instance is raised via side_effect for
    that call.
    """
    client_instance = MagicMock()

    def _as_side_effect(effect):
        if effect is None:
            return None
        if isinstance(effect, list):
            # `_seq` is deliberately a real closure variable (not a function
            # parameter) so it persists and is progressively popped across
            # repeated calls to `_iter_effect` as this mock's side_effect.
            _seq = list(effect)

            def _iter_effect(*_a, **_kw):
                item = _seq.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            return _iter_effect
        if isinstance(effect, Exception):
            return effect
        return lambda *a, **kw: effect

    get_side_effect = _as_side_effect(get_effect)
    post_side_effect = _as_side_effect(post_effect)

    client_instance.get = AsyncMock(side_effect=get_side_effect)
    client_instance.post = AsyncMock(side_effect=post_side_effect)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    async_client_cls = MagicMock(return_value=cm)
    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", async_client_cls)
    return client_instance


def _make_response(*, json_data=None, content=b"", raise_error=None):
    """Build a MagicMock standing in for an httpx.Response."""
    resp = MagicMock()
    if raise_error is not None:
        resp.raise_for_status.side_effect = raise_error
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_data if json_data is not None else {}
    resp.content = content
    return resp


def _build_raw_email_bytes():
    """A multipart email with:
      - one real attachment with actual content (should be forwarded)
      - one real attachment with empty content (get_payload(decode=True) is
        falsy -> must be skipped, covers the `if not content: continue` branch)
      - one inline attachment (already embedded in the html -> must be skipped)
    """
    msg = email.message.EmailMessage(policy=email_policy.default)
    msg["Subject"] = "Test"
    msg["From"] = "a@b.com"
    msg["To"] = "support@example.com"
    msg.set_content("hello body")
    msg.add_attachment(
        b"filedata123", maintype="application", subtype="octet-stream", filename="doc.pdf"
    )
    msg.add_attachment(
        b"", maintype="application", subtype="octet-stream", filename="empty.bin"
    )
    msg.add_attachment(
        b"imgdata456",
        maintype="image",
        subtype="png",
        filename="inline.png",
        disposition="inline",
        cid="abc123",
    )
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Signature verification failures
# ---------------------------------------------------------------------------

async def test_invalid_signature_returns_400(client, monkeypatch):
    _install_fake_webhook(monkeypatch, side_effect=WebhookVerificationError("bad sig"))

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b'{"type": "email.received"}', headers=_webhook_headers()
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook signature"}


async def test_invalid_signature_value_error_returns_400(client, monkeypatch):
    """Malformed (non-base64) signature/header values raise ValueError, not
    WebhookVerificationError — the route explicitly catches both."""
    _install_fake_webhook(monkeypatch, side_effect=ValueError("malformed header"))

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b'{"type": "email.received"}', headers=_webhook_headers()
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook signature"}


# ---------------------------------------------------------------------------
# Event-type / recipient filtering
# ---------------------------------------------------------------------------

async def test_non_email_received_event_is_ignored(client, monkeypatch):
    _install_fake_webhook(monkeypatch, return_value={"type": "email.sent", "data": {}})

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


async def test_recipient_not_in_allowlist_is_ignored(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Hi",
                "email_id": "email_1",
                "to": ["random@negolah.my"],
            },
        },
    )
    # Sanity: also make sure a real network call would blow up the test if
    # it were somehow reached, by NOT patching AsyncClient at all — if the
    # route incorrectly proceeded to forward, this test would hang/fail on
    # a real network call rather than silently passing.

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


async def test_missing_to_field_is_ignored(client, monkeypatch):
    """`data.get("to") or []` — a missing/empty "to" list must not crash and
    must be treated as no allowed recipients."""
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Hi",
                "email_id": "email_1",
                # no "to" key at all
            },
        },
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}


# ---------------------------------------------------------------------------
# Happy path forwarding
# ---------------------------------------------------------------------------

async def test_happy_path_forwarding_no_attachments(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Need help",
                "email_id": "email_42",
                "to": ["support@example.com"],
            },
        },
    )

    fetch_resp = _make_response(
        json_data={
            "html": "<p>hello</p>",
            "text": "hello",
            "attachments": [],
            "raw": {},
        }
    )
    send_resp = _make_response(json_data={"id": "sent_1"})

    client_instance = _install_fake_async_client(
        monkeypatch, get_effect=[fetch_resp], post_effect=[send_resp]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Only one GET (metadata fetch) — no download_url/real attachments so no
    # second GET for the raw message.
    assert client_instance.get.await_count == 1
    fetch_call = client_instance.get.await_args_list[0]
    assert fetch_call.args[0] == "https://api.resend.com/emails/receiving/email_42"
    assert fetch_call.kwargs["headers"] == {"Authorization": "Bearer re_test_dummy"}
    assert fetch_call.kwargs["params"] == {"html_format": "data_uri"}

    assert client_instance.post.await_count == 1
    post_call = client_instance.post.await_args_list[0]
    assert post_call.args[0] == "https://api.resend.com/emails"
    sent_json = post_call.kwargs["json"]
    assert sent_json["from"] == "noreply@example.com"
    assert sent_json["to"] == "forward-to@example.com"
    assert sent_json["reply_to"] == "sender@example.com"
    assert sent_json["subject"] == "[support@example.com] Need help"
    assert sent_json["html"] == "<p>hello</p>"
    assert sent_json["text"] == "hello"
    assert "attachments" not in sent_json


async def test_happy_path_falls_back_to_pre_wrapped_text_when_no_html(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Plain text mail",
                "email_id": "email_99",
                "to": ["support@example.com"],
            },
        },
    )

    fetch_resp = _make_response(
        json_data={"html": None, "text": "just plain text", "attachments": [], "raw": {}}
    )
    send_resp = _make_response(json_data={"id": "sent_2"})

    client_instance = _install_fake_async_client(
        monkeypatch, get_effect=[fetch_resp], post_effect=[send_resp]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    sent_json = client_instance.post.await_args_list[0].kwargs["json"]
    assert sent_json["html"] == "<pre>just plain text</pre>"


async def test_happy_path_multiple_allowed_recipients_tagged_together(client, monkeypatch):
    monkeypatch.setattr(
        webhooks_module,
        "RESEND_ALLOWED_RECIPIENTS",
        {"support@example.com", "admin@example.com"},
    )
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Broadcast",
                "email_id": "email_7",
                "to": ["support@example.com", "admin@example.com", "random@negolah.my"],
            },
        },
    )

    fetch_resp = _make_response(
        json_data={"html": "<p>hi</p>", "text": "hi", "attachments": [], "raw": {}}
    )
    send_resp = _make_response(json_data={"id": "sent_3"})

    client_instance = _install_fake_async_client(
        monkeypatch, get_effect=[fetch_resp], post_effect=[send_resp]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    sent_json = client_instance.post.await_args_list[0].kwargs["json"]
    assert sent_json["subject"] == "[support@example.com, admin@example.com] Broadcast"


async def test_happy_path_with_real_and_inline_attachments(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "With attachment",
                "email_id": "email_5",
                "to": ["support@example.com"],
            },
        },
    )

    raw_bytes = _build_raw_email_bytes()

    fetch_resp = _make_response(
        json_data={
            "html": "<p>see attached</p>",
            "text": "see attached",
            "attachments": [
                {"content_disposition": "attachment", "filename": "doc.pdf"},
                {"content_disposition": "attachment", "filename": "empty.bin"},
                {"content_disposition": "inline", "filename": "inline.png"},
            ],
            "raw": {"download_url": "https://api.resend.com/raw/email_5"},
        }
    )
    raw_resp = _make_response(content=raw_bytes)
    send_resp = _make_response(json_data={"id": "sent_4"})

    client_instance = _install_fake_async_client(
        monkeypatch, get_effect=[fetch_resp, raw_resp], post_effect=[send_resp]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Two GETs: metadata fetch, then raw message download.
    assert client_instance.get.await_count == 2
    raw_call = client_instance.get.await_args_list[1]
    assert raw_call.args[0] == "https://api.resend.com/raw/email_5"

    sent_json = client_instance.post.await_args_list[0].kwargs["json"]
    assert len(sent_json["attachments"]) == 1
    attachment = sent_json["attachments"][0]
    assert attachment["filename"] == "doc.pdf"
    assert attachment["content_type"] == "application/octet-stream"

    import base64
    assert base64.b64decode(attachment["content"]) == b"filedata123"


async def test_no_download_url_skips_raw_fetch_even_with_real_attachments(client, monkeypatch):
    """real_attachments present but no raw.download_url -> only the metadata
    GET happens; no crash, no attachments forwarded."""
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "No raw url",
                "email_id": "email_6",
                "to": ["support@example.com"],
            },
        },
    )

    fetch_resp = _make_response(
        json_data={
            "html": "<p>hi</p>",
            "text": "hi",
            "attachments": [{"content_disposition": "attachment", "filename": "doc.pdf"}],
            "raw": {},
        }
    )
    send_resp = _make_response(json_data={"id": "sent_5"})

    client_instance = _install_fake_async_client(
        monkeypatch, get_effect=[fetch_resp], post_effect=[send_resp]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 200
    assert client_instance.get.await_count == 1
    sent_json = client_instance.post.await_args_list[0].kwargs["json"]
    assert "attachments" not in sent_json


# ---------------------------------------------------------------------------
# Forwarding failure -> 503
# ---------------------------------------------------------------------------

async def test_httpx_error_on_fetch_returns_503(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Boom",
                "email_id": "email_err",
                "to": ["support@example.com"],
            },
        },
    )

    _install_fake_async_client(
        monkeypatch, get_effect=[httpx.HTTPError("network exploded")]
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Forwarding failed, retry"}


async def test_httpx_error_on_fetch_raise_for_status_returns_503(client, monkeypatch):
    """HTTPStatusError raised from raise_for_status() is also an httpx.HTTPError subclass."""
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Boom",
                "email_id": "email_err2",
                "to": ["support@example.com"],
            },
        },
    )

    bad_fetch_resp = _make_response(
        raise_error=httpx.HTTPStatusError(
            "500 error", request=MagicMock(), response=MagicMock(status_code=500)
        )
    )

    _install_fake_async_client(monkeypatch, get_effect=[bad_fetch_resp])

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Forwarding failed, retry"}


async def test_httpx_error_on_send_returns_503(client, monkeypatch):
    _install_fake_webhook(
        monkeypatch,
        return_value={
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Boom",
                "email_id": "email_err3",
                "to": ["support@example.com"],
            },
        },
    )

    fetch_resp = _make_response(
        json_data={"html": "<p>hi</p>", "text": "hi", "attachments": [], "raw": {}}
    )

    _install_fake_async_client(
        monkeypatch,
        get_effect=[fetch_resp],
        post_effect=[httpx.HTTPError("send failed")],
    )

    response = await client.post(
        RESEND_WEBHOOK_URL, content=b"{}", headers=_webhook_headers()
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Forwarding failed, retry"}
