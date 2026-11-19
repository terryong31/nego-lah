"""Shared lazy StripeClient factory for the backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stripe import StripeClient

_client: StripeClient | None = None


def get_stripe_client() -> StripeClient:
    """Return the process-wide StripeClient, created lazily on first use."""
    global _client
    if _client is None:
        from stripe import StripeClient

        from core.env import STRIPE_API_KEY

        # StripeClient(None) raises AuthenticationError at construction; coerce
        # unset env to "" so import/boot/schema scripts never crash while real
        # unconfigured API calls still fail closed with AuthenticationError.
        _client = StripeClient(STRIPE_API_KEY or "")
    return _client
