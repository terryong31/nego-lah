"""Identity domain: user accounts, auth middleware, admin sessions, and 2FA.

Authentication is identity's job, and every other domain's routes depend on it,
so the FastAPI dependencies are part of this domain's PUBLIC surface — other
domains import them from `domains.identity`, never from the modules inside it.
"""

from domains._lazy import lazy_getattr

_EXPORTS = {
    "IdentityService": ("domains.identity.services", "IdentityService"),
    # Auth dependencies — the identity domain's public contract.
    "verify_admin": ("domains.identity.admin_session", "verify_admin"),
    "write_audit": ("domains.identity.admin_session", "write_audit"),
    "verify_user_token": ("domains.identity.auth_middleware", "verify_user_token"),
    "get_user_id_from_body_or_token": (
        "domains.identity.auth_middleware",
        "get_user_id_from_body_or_token",
    ),
    "get_optional_user_id": ("domains.identity.auth_middleware", "get_optional_user_id"),
    "get_user_preferred_language": ("domains.identity.routes", "get_user_preferred_language"),
    # Routers.
    "user_router": ("domains.identity.routes", "router"),
    "auth_router": ("domains.identity.auth_routes", "router"),
    "admin_auth_router": ("domains.identity.admin_auth", "router"),
    "admin_users_router": ("domains.identity.admin_users", "router"),
}

__getattr__ = lazy_getattr(__name__, _EXPORTS)
__all__ = list(_EXPORTS)
