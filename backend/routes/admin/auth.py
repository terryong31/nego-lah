"""Admin authentication: password (factor 1) -> email OTP (factor 2) -> session cookie.

The only routes in the admin surface that are NOT gated by `verify_admin` —
they are what establishes the session everything else requires. Access is
guarded by 2FA, login rate limiting and an audit trail rather than an IP
allowlist.
"""

from fastapi import APIRouter, Depends, Request, Response

from admin_session import (
    clear_session,
    client_ip,
    enforce_login_rate_limit,
    password_then_send_otp,
    verify_admin,
    verify_otp_and_open_session,
    write_audit,
)
from core.security import verify_turnstile
from csrf import generate_csrf_token, set_csrf_cookie
from schemas import Admin2FARequest, AdminLoginRequest

router = APIRouter()


@router.post("/auth/login", dependencies=[Depends(verify_turnstile)])
def admin_login(request: AdminLoginRequest, req: Request):
    """Factor 1. Verify password + admin role, then email a 6-digit OTP.

    Returns an opaque pre-auth handle to use with /auth/verify-2fa. The response
    is intentionally identical whether or not the email is a real admin.

    Turnstile-gated (SPEC-044 D): the only unauthenticated credential endpoint
    in the system, and the one whose per-IP throttle was bypassable by rotating
    `X-Forwarded-For` until `client_ip` stopped reading that header. Unlike
    /chat/stream this is a one-shot submission, so a single-use siteverify
    token is the right shape for it. Bypassed in development, and open rather
    than closed when Cloudflare itself is unreachable — see verify_turnstile.
    """
    email = request.email.strip().lower()
    enforce_login_rate_limit(email, client_ip(req))
    handle = password_then_send_otp(email, request.password)
    return {"handle": handle, "message": "A verification code has been emailed to you."}


@router.post("/auth/verify-2fa")
def admin_verify_2fa(request: Admin2FARequest, req: Request, response: Response):
    """Factor 2. Verify the email OTP and open the admin session cookie."""
    result = verify_otp_and_open_session(request.handle, request.code.strip(), response, req)
    return {"valid": True, "email": result["email"]}


@router.post("/auth/logout")
def admin_logout(req: Request, response: Response, admin: dict = Depends(verify_admin)):
    """Invalidate the current admin session."""
    write_audit(admin.get("user_id"), admin.get("email"), "logout", None, admin.get("ip"))
    clear_session(req, response)
    return {"message": "Logged out"}


@router.get("/auth/session")
def admin_session(req: Request, response: Response, admin: dict = Depends(verify_admin)):
    """Lightweight check used by the frontend route middleware."""
    from env import ADMIN_COOKIE_NAME
    sid = req.cookies.get(ADMIN_COOKIE_NAME, "")
    if sid:
        token = generate_csrf_token(sid)
        set_csrf_cookie(response, token)
    return {"valid": True, "email": admin.get("email")}


@router.get("/auth/csrf")
def admin_csrf_token(req: Request, response: Response, admin: dict = Depends(verify_admin)):
    """Return a fresh CSRF token. Called on page refresh when the cookie may be stale."""
    from env import ADMIN_COOKIE_NAME
    sid = req.cookies.get(ADMIN_COOKIE_NAME, "")
    token = generate_csrf_token(sid)
    set_csrf_cookie(response, token)
    return {"csrf_token": token}
