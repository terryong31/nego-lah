
from pydantic import BaseModel

# ============================================
# ITEMS
# ============================================

class CreateItemSchema(BaseModel):
    name: str
    description: str
    condition: str
    images: str
    price: float | None = None
    min_price: float | None = None
    translations: dict | None = None


class ImageReorderRequest(BaseModel):
    ordered_urls: list[str]


# ============================================
# CHAT
# ============================================

class ChatRequest(BaseModel):
    user_id: str  # Unique identifier for the buyer
    message: str  # The buyer's message
    item_id: str | None = None  # Optional item ID being discussed


# ============================================
# PAYMENT
# ============================================

class CheckoutRequest(BaseModel):
    item_id: str  # Only need the item ID to look up price in database
    user_id: str | None = None  # User ID of the buyer (for webhook tracking)


# ============================================
# USER ACCOUNT (service-role operations, JWT-protected)
# ============================================

class PasswordUpdateSchema(BaseModel):
    current_password: str
    new_password: str


class EmailUpdateSchema(BaseModel):
    new_email: str
    # SPEC-056 #3: an access token alone must not be able to move the address
    # the account is recovered through.
    current_password: str


class AccountDeleteSchema(BaseModel):
    # SPEC-056 #7: deletion is irreversible, so it costs the password too.
    current_password: str


class LanguageUpdateSchema(BaseModel):
    language: str


# ============================================
# ADMIN
# ============================================

class AdminLoginRequest(BaseModel):
    email: str
    password: str


class Admin2FARequest(BaseModel):
    handle: str
    code: str


class BanRequest(BaseModel):
    is_banned: bool


class AIToggleRequest(BaseModel):
    ai_enabled: bool


class AdminMessageRequest(BaseModel):
    message: str


class AdminReadStateRequest(BaseModel):
    """SPEC-053 — set or clear a conversation's read watermark.

    Defaults to True so the common call (the console opening a thread) can post
    an empty body.
    """
    read: bool = True


class UserProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None


class OrderStatusUpdate(BaseModel):
    status: str  # pending_info, confirmed, shipped, delivered


class OrderUpdate(BaseModel):
    item_name: str | None = None
    amount: float | None = None
    status: str | None = None
    # Backend field names (original)
    shipping_address: str | None = None
    shipping_phone: str | None = None
    shipping_name: str | None = None
    # Frontend field names (aliases)
    address: str | None = None
    phone: str | None = None
    recipient_name: str | None = None
    notes: str | None = None


class ShipmentUpdate(BaseModel):
    """Postage as the seller records it (SPEC-057).

    `tracking_url` is optional because it is usually derivable from the courier;
    `notify` exists so a correction to an already-announced shipment doesn't
    email the buyer a second time.
    """

    courier: str
    tracking_number: str
    tracking_url: str | None = None
    notify: bool = True


class MarketValuationRequest(BaseModel):
    query: str
    condition: str = "good"
    category: str | None = None
