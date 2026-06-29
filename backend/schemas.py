from pydantic import BaseModel
from typing import Optional, List


# ============================================
# ITEMS
# ============================================

class CreateItemSchema(BaseModel):
    name: str
    description: str
    condition: str
    images: str
    price: Optional[float] = None
    min_price: Optional[float] = None


class UpdateItemSchema(BaseModel):
    """All fields optional - only provided fields are updated."""
    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[str] = None
    images: Optional[str] = None
    price: Optional[float] = None
    min_price: Optional[float] = None


class ImageReorderRequest(BaseModel):
    ordered_urls: List[str]


# ============================================
# CHAT
# ============================================

class ChatRequest(BaseModel):
    user_id: str  # Unique identifier for the buyer
    message: str  # The buyer's message
    item_id: Optional[str] = None  # Optional item ID being discussed


# ============================================
# PAYMENT
# ============================================

class CheckoutRequest(BaseModel):
    item_id: str  # Only need the item ID to look up price in database
    user_id: Optional[str] = None  # User ID of the buyer (for webhook tracking)


# ============================================
# USER ACCOUNT (service-role operations, JWT-protected)
# ============================================

class PasswordUpdateSchema(BaseModel):
    current_password: str
    new_password: str


class EmailUpdateSchema(BaseModel):
    new_email: str


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


class UserProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    status: str  # pending_info, confirmed, shipped, delivered


class OrderUpdate(BaseModel):
    item_name: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    # Backend field names (original)
    shipping_address: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_name: Optional[str] = None
    # Frontend field names (aliases)
    address: Optional[str] = None
    phone: Optional[str] = None
    recipient_name: Optional[str] = None
    notes: Optional[str] = None


class MarketValuationRequest(BaseModel):
    query: str
    condition: str = "good"
    category: Optional[str] = None
