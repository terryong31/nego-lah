"""
Bounded contexts of the Nego-Lah Modular Monolith (ADR-0002, SPEC-002).

Each domain owns its own business logic, persistence access and routers:

    catalog      items, search, inventory, shipping couriers
    negotiation  the agent, its tools and sub-agents, chat memory
    billing      Stripe checkout, payment state, fulfillment, refunds
    identity     accounts, admin sessions, auth middleware, 2FA
    webhooks     inbound webhook handlers

Shared infrastructure (config, cache, connectors, logging, security) lives in
`core/` and may be imported by any domain. A domain must never reach into
another domain's tables or private modules — cross-domain work goes through the
other domain's exported service. `tests/test_domain_boundaries.py` enforces
this by AST-scanning every `.table("…")` call in the backend.

Every domain package resolves its routers and services through `__getattr__`.
The logic now lives *inside* these packages, so an eager import in `__init__`
would run the whole domain (and its routers, and their dependencies) before the
first submodule finished importing — a guaranteed circular import.
"""

__all__ = ["catalog", "billing", "negotiation", "identity", "webhooks"]
