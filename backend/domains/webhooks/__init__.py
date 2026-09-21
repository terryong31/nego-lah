"""Webhooks domain: inbound webhook handlers (Resend inbound email)."""

from domains._lazy import lazy_getattr

_EXPORTS = {"webhooks_router": ("domains.webhooks.routes", "router")}

__getattr__ = lazy_getattr(__name__, _EXPORTS)
__all__ = list(_EXPORTS)
