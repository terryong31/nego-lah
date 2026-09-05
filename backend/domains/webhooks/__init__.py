"""
Webhooks domain: Inbound webhook handlers for Stripe and Resend.
"""
from routes.webhooks import router as webhooks_router

__all__ = ["webhooks_router"]
