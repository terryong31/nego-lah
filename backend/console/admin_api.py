"""Admin API surface — application composition, not a domain.

The admin console spans every bounded context (catalogue CRUD, orders, chats,
users, dashboard), so the router that assembles it sits beside `main.py` rather
than inside any one domain. Each domain owns and exports its own admin routes;
this module only decides what is public and what is gated.

The gating lives here rather than in the domains, so there is exactly one place
to read what is reachable without a session:

  * the identity domain's `admin_auth` router mounts directly on the public
    router — those routes are what establish a session, so they cannot require
    one.
  * every other domain's admin router mounts on `protected`, which carries
    `verify_admin` + `verify_csrf_token` for all of its routes.

A domain therefore declares a plain `APIRouter()` and never has to remember to
gate itself; forgetting to include it here is a 404, not an open endpoint.
That property is why nothing else mounts these routers — `tests/test_admin_gating.py`
asserts every admin data route carries both dependencies.

Each router is taken from its domain's package rather than the module inside it:
`domains/<name>/__init__.py` is the contract, and composition code is held to it
like everything else (SPEC-095).
"""

from fastapi import APIRouter, Depends

from console.admin_ai import router as ai_router
from console.admin_dashboard import router as dashboard_router
from console.admin_listings import router as listings_router
from core.csrf import verify_csrf_token
from core.env import ADMIN_PREFIX
from domains.billing import admin_orders_router as orders_router
from domains.catalog import admin_items_router as items_router
from domains.identity import admin_auth_router as auth_router
from domains.identity import admin_users_router as users_router
from domains.identity import verify_admin
from domains.negotiation import admin_chats_router as chats_router

# Public router. There is no IP allowlist; access is gated by 2FA + rate
# limiting + audit.
router = APIRouter(prefix=ADMIN_PREFIX, tags=["System"])

# Every data route requires a valid admin session + CSRF verification.
protected = APIRouter(dependencies=[Depends(verify_admin), Depends(verify_csrf_token)])

router.include_router(auth_router)

for _domain_router in (users_router, chats_router, orders_router, listings_router, dashboard_router, items_router, ai_router):
    protected.include_router(_domain_router)

# Mount the verify_admin-gated routes under the same prefix as the auth routes.
router.include_router(protected)

__all__ = ["router", "protected"]
