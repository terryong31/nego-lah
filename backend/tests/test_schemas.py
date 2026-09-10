"""Tests for schemas.py — pure Pydantic models, no functions.

Every model is instantiated with valid data and its fields are asserted to
round-trip. A handful of models are also checked for ValidationError when a
required field is missing.
"""

import pytest
from pydantic import ValidationError

from schemas import (
    AccountDeleteSchema,
    Admin2FARequest,
    AdminLoginRequest,
    AdminMessageRequest,
    AIToggleRequest,
    BanRequest,
    ChatRequest,
    CheckoutRequest,
    CreateItemSchema,
    EmailUpdateSchema,
    ImageReorderRequest,
    MarketValuationRequest,
    OrderStatusUpdate,
    OrderUpdate,
    PasswordUpdateSchema,
    UserProfileUpdateRequest,
)

# ============================================
# ITEMS
# ============================================

def test_create_item_schema_full():
    s = CreateItemSchema(
        name="Vintage Chair",
        description="A comfy chair",
        condition="used",
        images="https://example.com/img.jpg",
        price=100.0,
        min_price=50.0,
    )
    assert s.name == "Vintage Chair"
    assert s.description == "A comfy chair"
    assert s.condition == "used"
    assert s.images == "https://example.com/img.jpg"
    assert s.price == 100.0
    assert s.min_price == 50.0


def test_create_item_schema_optional_defaults():
    s = CreateItemSchema(
        name="Table",
        description="Wooden table",
        condition="new",
        images="https://example.com/table.jpg",
    )
    assert s.price is None
    assert s.min_price is None


def test_create_item_schema_missing_required_field_raises():
    with pytest.raises(ValidationError):
        CreateItemSchema(description="No name provided", condition="new", images="x")


def test_image_reorder_request():
    s = ImageReorderRequest(ordered_urls=["a.jpg", "b.jpg", "c.jpg"])
    assert s.ordered_urls == ["a.jpg", "b.jpg", "c.jpg"]


def test_image_reorder_request_missing_field_raises():
    with pytest.raises(ValidationError):
        ImageReorderRequest()


# ============================================
# CHAT
# ============================================

def test_chat_request_full():
    s = ChatRequest(user_id="u1", message="hello", item_id="item-1")
    assert s.user_id == "u1"
    assert s.message == "hello"
    assert s.item_id == "item-1"


def test_chat_request_optional_item_id_defaults_none():
    s = ChatRequest(user_id="u1", message="hello")
    assert s.item_id is None


# ============================================
# PAYMENT
# ============================================

def test_checkout_request_full():
    s = CheckoutRequest(item_id="item-1", user_id="u1")
    assert s.item_id == "item-1"
    assert s.user_id == "u1"


def test_checkout_request_user_id_optional():
    s = CheckoutRequest(item_id="item-1")
    assert s.user_id is None


# ============================================
# USER ACCOUNT
# ============================================

def test_password_update_schema():
    s = PasswordUpdateSchema(current_password="old", new_password="new")
    assert s.current_password == "old"
    assert s.new_password == "new"


def test_password_update_schema_missing_field_raises():
    with pytest.raises(ValidationError):
        PasswordUpdateSchema(current_password="old")


def test_email_update_schema():
    s = EmailUpdateSchema(new_email="new@example.com", current_password="oldpass123")
    assert s.new_email == "new@example.com"
    assert s.current_password == "oldpass123"


def test_email_update_schema_requires_the_current_password():
    """SPEC-056 #3: an email change that does not re-authenticate is an account
    takeover waiting for one stolen token, so the field is not optional."""
    with pytest.raises(ValidationError):
        EmailUpdateSchema(new_email="new@example.com")


def test_account_delete_schema_requires_the_current_password():
    with pytest.raises(ValidationError):
        AccountDeleteSchema()
    assert AccountDeleteSchema(current_password="oldpass123").current_password == "oldpass123"


# ============================================
# ADMIN
# ============================================

def test_admin_login_request():
    s = AdminLoginRequest(email="admin@example.com", password="secret")
    assert s.email == "admin@example.com"
    assert s.password == "secret"


def test_admin_2fa_request():
    s = Admin2FARequest(handle="handle-123", code="000000")
    assert s.handle == "handle-123"
    assert s.code == "000000"


def test_ban_request_true():
    s = BanRequest(is_banned=True)
    assert s.is_banned is True


def test_ban_request_false():
    s = BanRequest(is_banned=False)
    assert s.is_banned is False


def test_ai_toggle_request():
    s = AIToggleRequest(ai_enabled=True)
    assert s.ai_enabled is True


def test_admin_message_request():
    s = AdminMessageRequest(message="Hello there")
    assert s.message == "Hello there"


def test_user_profile_update_request_defaults():
    s = UserProfileUpdateRequest()
    assert s.display_name is None
    assert s.avatar_url is None


def test_user_profile_update_request_full():
    s = UserProfileUpdateRequest(display_name="Terry", avatar_url="https://x/y.png")
    assert s.display_name == "Terry"
    assert s.avatar_url == "https://x/y.png"


def test_order_status_update():
    s = OrderStatusUpdate(status="confirmed")
    assert s.status == "confirmed"


def test_order_status_update_missing_field_raises():
    with pytest.raises(ValidationError):
        OrderStatusUpdate()


def test_order_update_defaults_all_none():
    s = OrderUpdate()
    assert s.item_name is None
    assert s.amount is None
    assert s.status is None
    assert s.shipping_address is None
    assert s.shipping_phone is None
    assert s.shipping_name is None
    assert s.address is None
    assert s.phone is None
    assert s.recipient_name is None
    assert s.notes is None


def test_order_update_backend_field_names():
    s = OrderUpdate(
        item_name="Widget",
        amount=42.0,
        status="shipped",
        shipping_address="123 Main St",
        shipping_phone="555-1234",
        shipping_name="Terry Ong",
        notes="Leave at door",
    )
    assert s.item_name == "Widget"
    assert s.amount == 42.0
    assert s.status == "shipped"
    assert s.shipping_address == "123 Main St"
    assert s.shipping_phone == "555-1234"
    assert s.shipping_name == "Terry Ong"
    assert s.notes == "Leave at door"
    # Frontend aliases are separate fields, not populated by backend names
    assert s.address is None
    assert s.phone is None
    assert s.recipient_name is None


def test_order_update_frontend_alias_field_names():
    s = OrderUpdate(
        address="456 Side St",
        phone="555-6789",
        recipient_name="Jane Doe",
    )
    assert s.address == "456 Side St"
    assert s.phone == "555-6789"
    assert s.recipient_name == "Jane Doe"
    # Backend fields are separate and remain unset
    assert s.shipping_address is None
    assert s.shipping_phone is None
    assert s.shipping_name is None


# ============================================
# MARKET VALUATION
# ============================================

def test_market_valuation_request_defaults():
    s = MarketValuationRequest(query="iPhone 12")
    assert s.query == "iPhone 12"
    assert s.condition == "good"
    assert s.category is None


def test_market_valuation_request_full():
    s = MarketValuationRequest(query="iPhone 12", condition="excellent", category="electronics")
    assert s.query == "iPhone 12"
    assert s.condition == "excellent"
    assert s.category == "electronics"


def test_market_valuation_request_missing_query_raises():
    with pytest.raises(ValidationError):
        MarketValuationRequest()
