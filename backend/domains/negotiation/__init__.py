"""Negotiation domain: the AI agent, its tools and sub-agents, memory, chat stream.

Everything resolves through `__getattr__`. Importing `bot` pulls the whole
LangChain/LangGraph stack — measured at +430 ms and +70 MB RSS per worker — and
`main.py` imports this package at boot only to mount a router.
"""

from domains._lazy import lazy_getattr

_EXPORTS = {
    # Bus wiring, called from main.py's lifespan (SPEC-097).
    "register_subscribers": ("domains.negotiation.subscribers", "register_subscribers"),
    "NegotiationService": ("domains.negotiation.services", "NegotiationService"),
    # Agent entry points.
    "chat": ("domains.negotiation.bot", "chat"),
    "chat_stream": ("domains.negotiation.bot", "chat_stream"),
    "get_chat_model": ("domains.negotiation.llm_factory", "get_chat_model"),
    "is_local_llm_available": ("domains.negotiation.llm_factory", "is_local_llm_available"),
    # Listing-authoring aids the catalogue console uses (SPEC-037).
    "analyze_listing": ("domains.negotiation.tools.listing_pipeline", "analyze_listing"),
    "image_analyzer": ("domains.negotiation.tools.image_analyzer", "image_analyzer"),
    "market_service": ("domains.negotiation.tools.market_price", "market_service"),
    # Routers.
    # `main.py`'s lifespan flushes due digests, so the sweep is public surface.
    "flush_due_digests": ("domains.negotiation.unread_digest", "flush_due_digests"),
    "UNREAD_DIGEST_SWEEP_SECONDS": ("domains.negotiation.unread_digest", "UNREAD_DIGEST_SWEEP_SECONDS"),
    "negotiation_router": ("domains.negotiation.routes", "router"),
    # Shutdown lets in-flight agent turns finish (audit REL-5).
    "drain_running_turns": ("domains.negotiation.routes", "drain_running_turns"),
    "admin_chats_router": ("domains.negotiation.admin_routes", "router"),
}

__getattr__ = lazy_getattr(__name__, _EXPORTS)
__all__ = list(_EXPORTS)
