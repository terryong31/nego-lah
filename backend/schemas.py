from pydantic import BaseModel
from typing import Optional


class UserSchema(BaseModel):
    username: str
    password: str


class ItemSchema(BaseModel):
    item_id: str
    name: str
    description: str
    condition: str
    images: str
    price: Optional[float] = None
    min_price: Optional[float] = None


class CheckoutRequest(BaseModel):
    item_id: str  # Only need the item ID to look up price in database
    user_id: Optional[str] = None  # User ID of the buyer (for webhook tracking)


class ChatRequest(BaseModel):
    user_id: str  # Unique identifier for the buyer
    message: str  # The buyer's message
    item_id: Optional[str] = None  # Optional item ID being discussed