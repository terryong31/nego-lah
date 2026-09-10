from unittest.mock import MagicMock, patch

from env import RESEND_FORWARD_TO
from services import email_service


def test_send_purchase_receipt_success():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        order = {
            "id": "order-123",
            "item_name": "Mechanical Keyboard",
            "amount": 150.0,
            "created_at": "2026-09-04T12:00:00Z",
        }
        res = email_service.send_purchase_receipt("buyer@example.com", order)

        assert res is True
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["to"] == ["buyer@example.com"]
        assert "Mechanical Keyboard" in payload["subject"]
        assert "RM150.00" in payload["html"]
        assert "order-123" in payload["html"]


def test_send_seller_sale_alert_success():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        order = {
            "id": "order-123",
            "item_name": "Mechanical Keyboard",
            "amount": 150.0,
            "buyer_email": "buyer@example.com",
            "buyer_id": "user-456",
        }
        res = email_service.send_seller_sale_alert(RESEND_FORWARD_TO or "seller@example.com", order)

        assert res is True
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "Mechanical Keyboard" in payload["subject"]
        assert "🎉" not in payload["subject"]
        assert "RM150.00" in payload["html"]
        assert "buyer@example.com" in payload["html"]
        # Brand styling assertions
        assert "#10b981" in payload["html"]
        assert "#f97316" not in payload["html"]
        assert "color: #ffffff" in payload["html"]
        assert "Item sold" in payload["html"]


def test_send_unread_message_email_success():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        res = email_service.send_unread_message_email(
            "buyer@example.com",
            "I can offer RM120 if you pick it up today!",
            item_name="Mechanical Keyboard"
        )

        assert res is True
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["to"] == ["buyer@example.com"]
        assert "RM120 if you pick it up" in payload["html"]


# ---------------------------------------------------------------------------
# SPEC-052 — the batched digest that replaced the per-message send
# ---------------------------------------------------------------------------

def _capture_send(fn, *args, **kwargs):
    """Run a sender against a mocked Resend and hand back its request payload."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = fn(*args, **kwargs)
        call_args = mock_client.post.call_args
        payload = (call_args.kwargs.get("json") or call_args[1].get("json")) if call_args else None
        return result, payload


def test_send_unread_digest_email_carries_every_message():
    res, payload = _capture_send(
        email_service.send_unread_digest_email,
        "buyer@example.com",
        [
            {"content": "hey, still keen?"},
            {"content": "I can do RM90"},
            {"content": "posting tomorrow if you are"},
        ],
        item_name="Mechanical Keyboard",
    )

    assert res is True
    assert payload["to"] == ["buyer@example.com"]
    # One email, three quotes.
    assert "3 new messages from the seller" in payload["subject"]
    assert "Mechanical Keyboard" in payload["subject"]
    for text in ("hey, still keen?", "I can do RM90", "posting tomorrow if you are"):
        assert text in payload["html"]


def test_send_unread_digest_email_reads_naturally_for_a_single_message():
    """A digest of one is the common case and must not say "1 new messages"."""
    res, payload = _capture_send(
        email_service.send_unread_digest_email,
        "buyer@example.com",
        [{"content": "Can we meet tomorrow?"}],
    )

    assert res is True
    assert payload["subject"] == "New message from the seller"
    assert "Can we meet tomorrow?" in payload["html"]
    assert "1 new messages" not in payload["html"]


def test_send_unread_digest_email_skips_empty_bodies():
    res, payload = _capture_send(
        email_service.send_unread_digest_email, "buyer@example.com", [{"content": "   "}, {}]
    )
    assert res is False
    assert payload is None


def test_send_human_transfer_alert_success():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {"id": "msg_transfer_123"}
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        res = email_service.send_human_transfer_alert(
            user_id="user_test_456",
            reason="Customer wants to speak to manager",
            user_email="buyer@example.com",
            summary="User asked for direct discussion on discount."
        )

        assert res is True
        assert mock_client.post.called
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "user_test_456" in payload["html"]
        assert "🚨" not in payload["subject"]
        assert "Needs your response" in payload["html"]
        assert "Customer wants to speak to manager" in payload["html"]
        assert "_console/chats?user=user_test_456" in payload["html"]
        assert "#10b981" in payload["html"]


def test_send_email_gracefully_handles_no_api_key(monkeypatch):
    monkeypatch.setattr(email_service, "RESEND_API_KEY", None)
    res = email_service.send_purchase_receipt("buyer@example.com", {"item_name": "Test", "amount": 10})
    assert res is False


def test_send_email_gracefully_handles_http_failure():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("Connection timeout")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        res = email_service.send_purchase_receipt("buyer@example.com", {"item_name": "Test", "amount": 10})
        assert res is False


def test_render_email_template_all_templates():
    receipt = email_service.render_email_template("purchase_receipt.html", {
        "subject": "Receipt",
        "item_name": "Vintage Camera",
        "amount": 250.0,
        "order_id": "ord_999",
        "date_str": "September 05, 2026",
        "chat_url": "https://example.com/chat",
        "orders_url": "https://example.com/orders",
    })
    assert "Payment received" in receipt
    assert "RM250.00" in receipt
    assert "Vintage Camera" in receipt
    assert "ord_999" in receipt
    assert "https://example.com/chat" in receipt

    alert = email_service.render_email_template("seller_sale_alert.html", {
        "subject": "Sale Alert",
        "item_name": "Vintage Camera",
        "amount": 250.0,
        "order_id": "ord_999",
        "buyer_email": "buyer@example.com",
        "date_str": "September 05, 2026",
        "admin_orders_url": "https://example.com/_console/orders",
    })
    assert "Item sold" in alert
    assert "RM250.00" in alert
    assert "buyer@example.com" in alert
    assert "https://example.com/_console/orders" in alert

    unread = email_service.render_email_template("unread_message.html", {
        "subject": "New Message",
        "message_snippet": "Can we meet tomorrow?",
        "item_name": "Vintage Camera",
        "chat_url": "https://example.com/chat",
    })
    assert "New message" in unread
    assert "Can we meet tomorrow?" in unread

    digest = email_service.render_email_template("unread_digest.html", {
        "subject": "2 new messages",
        "messages": [{"content": "Can we meet tomorrow?"}, {"content": "Or Friday?"}],
        "count": 2,
        "item_name": "Vintage Camera",
        "chat_url": "https://example.com/chat",
    })
    assert "2 new messages" in digest
    assert "Can we meet tomorrow?" in digest
    assert "Or Friday?" in digest
    # Same Ledger vocabulary as every other template (SPEC-049).
    assert "#10b981" in digest

    transfer = email_service.render_email_template("human_transfer_alert.html", {
        "subject": "Transfer",
        "user_id": "usr_123",
        "user_display": "Alice",
        "reason": "Technical inquiry",
        "summary": "User wants specs",
        "console_chat_url": "https://example.com/_console/chats?user=usr_123",
        "date_str": "September 05, 2026 12:00 UTC",
    })
    assert "Needs your response" in transfer
    assert "usr_123" in transfer
    assert "Technical inquiry" in transfer
    assert "User wants specs" in transfer


def test_email_template_renders_cdn_brand_logo():
    html = email_service.render_email_template("purchase_receipt.html", {
        "subject": "Receipt",
        "item_name": "Mechanical Keyboard",
        "amount": 150.0,
        "price_formatted": "RM150.00",
        "order_id": "ord_123",
        "order_date": "Sept 06, 2026",
    })
    # Must render brand logo image from Supabase Storage CDN
    assert "branding/logo.png" in html
    assert "<img src=" in html
    assert 'alt="Nego-lah"' in html
    assert 'width="24"' in html



# ---------------------------------------------------------------------------
# Shipment notices (SPEC-057)
# ---------------------------------------------------------------------------

def _resend_stub():
    """The httpx.Client patch every sender test in this file uses."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response
    return mock_client


def _sent_payload(mock_client):
    call_args = mock_client.post.call_args
    return call_args.kwargs.get("json") or call_args[1].get("json")


SHIPPED_ORDER = {
    "id": "order-777",
    "item_name": "Casio VX-4",
    "courier": "J&T Express",
    "tracking_number": "630123456789",
    "tracking_url": "https://www.jtexpress.my/tracking?billcode=630123456789",
}


def test_send_shipment_notice_carries_the_courier_and_a_track_button():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _resend_stub()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        assert email_service.send_shipment_notice("buyer@example.com", SHIPPED_ORDER) is True

        payload = _sent_payload(mock_client)
        assert payload["to"] == ["buyer@example.com"]
        assert "Casio VX-4" in payload["subject"]
        # Jinja autoescapes, so the ampersand in the carrier name arrives as an
        # entity — which is exactly what should reach an HTML mail client.
        assert "J&amp;T Express" in payload["html"]
        assert "J&T Express" not in payload["html"]
        assert "630123456789" in payload["html"]
        assert "https://www.jtexpress.my/tracking?billcode=630123456789" in payload["html"]
        assert "Track your parcel" in payload["html"]


def test_send_shipment_notice_derives_a_missing_tracking_url():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _resend_stub()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        email_service.send_shipment_notice(
            "buyer@example.com", {**SHIPPED_ORDER, "tracking_url": None}
        )

        assert "630123456789" in _sent_payload(mock_client)["html"]


def test_send_shipment_notice_falls_back_to_the_chat_when_there_is_no_link():
    """An unknown courier still gets a usable email — just not a track button."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _resend_stub()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        email_service.send_shipment_notice(
            "buyer@example.com",
            {**SHIPPED_ORDER, "courier": "Some Local Bike Guy", "tracking_url": None},
        )

        html = _sent_payload(mock_client)["html"]
        assert "Some Local Bike Guy" in html
        assert "Track your parcel" not in html
        assert "Open chat" in html


def test_send_shipment_notice_words_a_delivery_as_a_delivery():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _resend_stub()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        email_service.send_shipment_notice("buyer@example.com", SHIPPED_ORDER, delivered=True)

        payload = _sent_payload(mock_client)
        assert "delivered" in payload["subject"].lower()
        assert "delivered" in payload["html"].lower()


def test_send_shipment_notice_without_a_recipient_is_a_no_op():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = _resend_stub()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        assert email_service.send_shipment_notice("", SHIPPED_ORDER) is False
        assert not mock_client.post.called


def test_shipment_template_renders_without_a_courier_or_tracking_number():
    """The seller may only know the status. The template must not break on it."""
    html = email_service.render_email_template("shipment_notice.html", {
        "subject": "On its way",
        "item_name": "Casio VX-4",
        "order_id": "order-777",
        "courier": None,
        "tracking_number": None,
        "tracking_url": None,
        "date_str": "September 10, 2026",
        "chat_url": "https://negolah.my/chat",
        "orders_url": "https://negolah.my/orders",
        "delivered": False,
    })
    assert "Casio VX-4" in html
    assert "Open chat" in html
