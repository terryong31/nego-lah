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
        assert "RM150.00" in payload["html"]
        assert "buyer@example.com" in payload["html"]
        # Brand styling assertions
        assert "#10b981" in payload["html"]
        assert "#f97316" not in payload["html"]
        assert "color: #ffffff" in payload["html"]
        assert "Sale Confirmed" in payload["html"]


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
        assert "Human Intervention Needed" in payload["html"]
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
    assert "Payment Confirmed" in receipt
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
    assert "Sale Confirmed" in alert
    assert "RM250.00" in alert
    assert "buyer@example.com" in alert
    assert "https://example.com/_console/orders" in alert

    unread = email_service.render_email_template("unread_message.html", {
        "subject": "New Message",
        "message_snippet": "Can we meet tomorrow?",
        "item_name": "Vintage Camera",
        "chat_url": "https://example.com/chat",
    })
    assert "New Message" in unread
    assert "Can we meet tomorrow?" in unread

    transfer = email_service.render_email_template("human_transfer_alert.html", {
        "subject": "Transfer",
        "user_id": "usr_123",
        "user_display": "Alice",
        "reason": "Technical inquiry",
        "summary": "User wants specs",
        "console_chat_url": "https://example.com/_console/chats?user=usr_123",
        "date_str": "September 05, 2026 12:00 UTC",
    })
    assert "Human Intervention Needed" in transfer
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
    assert 'width="32"' in html

