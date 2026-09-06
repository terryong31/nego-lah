"""Admin API surface.

This was one 978-line module covering seven unrelated concerns — auth, users,
chat, orders, listing aids, dashboard, catalogue CRUD. It is now one module per
concern, assembled here (SPEC-037). Every URL, dependency and response is
unchanged: `main.py` still does `from routes.admin import router`.

The gating lives here rather than in the submodules, so there is exactly one
place to read what is public and what is not:

  * `auth.router` mounts directly on the public router — those routes are what
    establish a session, so they cannot require one.
  * every other submodule mounts on `protected`, which carries
    `verify_admin` + `verify_csrf_token` for all of its routes.

A submodule therefore declares a plain `APIRouter()` and never has to remember
to gate itself; forgetting to include it here is a 404, not an open endpoint.
"""

from fastapi import APIRouter, Depends

from admin_session import verify_admin
from csrf import verify_csrf_token
from env import ADMIN_PREFIX

from . import auth, chats, dashboard, items, listings, orders, users

# Public router. There is no IP allowlist; access is gated by 2FA + rate
# limiting + audit.
router = APIRouter(prefix=ADMIN_PREFIX, tags=["System"])

# Every data route requires a valid admin session + CSRF verification.
protected = APIRouter(dependencies=[Depends(verify_admin), Depends(verify_csrf_token)])

router.include_router(auth.router)

for _module in (users, chats, orders, listings, dashboard, items):
    protected.include_router(_module.router)

# Mount the verify_admin-gated routes under the same prefix as the auth routes.
router.include_router(protected)

__all__ = ["router", "protected"]
