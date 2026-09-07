"""
Admin authentication & session management.

Security model (see supabase/README.md):
  * Admins are ordinary Supabase users flagged with app_metadata.role == "admin"
    (set server-side via the service role; users cannot write app_metadata).
  * Login is two-factor: password (factor 1) then an email OTP (factor 2),
    both via Supabase auth. Neither factor alone grants access.
  * On success we mint an OPAQUE session id stored in Redis and returned as an
    httpOnly Secure cookie. The cookie carries no JWT, so revocation is instant
    (delete the Redis key) and there is no token for XSS to steal.
  * A Redis allowlist (`admin:allow:{user_id}`) is checked on every request,
    giving instant revocation independent of JWT expiry. It self-heals from
    Supabase app_metadata on each successful login.

There is deliberately no IP allowlist — access is gated by the factors above
plus rate limiting, audit logging, and the layers documented in the README.
"""
import json
import re
import secrets
from pathlib import Path

import httpx
from fastapi import HTTPException, Request, Response
from supabase import create_client

from cache import check_rate_limit, redis_client
from connector import admin_supabase
from csrf import clear_csrf, generate_csrf_token, set_csrf_cookie
from env import (
    ADMIN_COOKIE_DOMAIN,
    ADMIN_COOKIE_NAME,
    ADMIN_COOKIE_PATH,
    ADMIN_COOKIE_SAMESITE,
    ADMIN_COOKIE_SECURE,
    ADMIN_PREAUTH_TTL,
    ADMIN_SESSION_TTL,
    RESEND_API_KEY,
    RESEND_FORWARD_FROM,
    SUPABASE_URL,
    USER_SUPABASE_KEY,
)
from logger import logger

# Redis key prefixes
_SESS_KEY = "admin:sess:"        # sid -> {user_id, email}
_PREAUTH_KEY = "admin:preauth:"  # handle -> email (between factor 1 and 2)
_ALLOW_KEY = "admin:allow:"      # user_id -> email (admin allowlist, revocable)

# Allowlist entries persist long enough to survive normal operation and are
# re-asserted from Supabase on every login, so a Redis flush self-heals.
_ALLOW_TTL = 90 * 24 * 3600

# Rate limits
_LOGIN_MAX, _LOGIN_WINDOW = 5, 900   # 5 password attempts / 15 min per email+IP
_OTP_MAX, _OTP_WINDOW = 5, 300       # 5 OTP attempts / 5 min per pre-auth handle


def _auth_client():
    """A throwaway anon client for auth calls, so we never mutate the shared
    service-role client's session state under concurrency."""
    return create_client(SUPABASE_URL, USER_SUPABASE_KEY)


def client_ip(request: Request) -> str:
    """The caller's address, as resolved by the server — never as claimed.

    Reading `X-Forwarded-For` here was a bypass: Caddy *appends* to whatever
    header the client sent, so the first value is attacker-chosen. Since this
    keys the admin login limiter (`adminlogin:{email}:{ip}`), rotating one
    header gave unlimited password attempts, and it forged the IP recorded in
    the audit log too.

    `request.client.host` is uvicorn's own answer. It applies X-Forwarded-For
    only for peers in `--forwarded-allow-ips` (see the Dockerfile), taking the
    last address a trusted proxy didn't add — which is the real client, and is
    not something the client can influence.
    """
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Admin allowlist (instant revocation, self-healing from Supabase)
# ---------------------------------------------------------------------------

def grant_admin(user_id: str, email: str = "") -> None:
    redis_client.setex(f"{_ALLOW_KEY}{user_id}", _ALLOW_TTL, email or "1")


def revoke_admin(user_id: str) -> None:
    redis_client.delete(f"{_ALLOW_KEY}{user_id}")


def is_allowed_admin(user_id: str) -> bool:
    return redis_client.get(f"{_ALLOW_KEY}{user_id}") is not None


def _is_admin_user(user) -> bool:
    """Authoritative role check against Supabase app_metadata."""
    meta = getattr(user, "app_metadata", None) or {}
    return meta.get("role") == "admin"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def enforce_login_rate_limit(email: str, ip: str) -> None:
    if not check_rate_limit(f"adminlogin:{email}:{ip}", _LOGIN_MAX, _LOGIN_WINDOW):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


def enforce_otp_rate_limit(handle: str) -> None:
    if not check_rate_limit(f"admin2fa:{handle}", _OTP_MAX, _OTP_WINDOW):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


# ---------------------------------------------------------------------------
# Factor 1: password  ->  pre-auth handle + emailed OTP
# ---------------------------------------------------------------------------

def password_then_send_otp(email: str, password: str) -> str:
    """
    Verify the password (factor 1), confirm the account is an admin, then send an
    email OTP (factor 2). Returns a short-lived pre-auth handle.

    Raises 401 with a GENERIC message in every failure case so we never reveal
    whether the email exists or is an admin.
    """
    generic = HTTPException(status_code=401, detail="Invalid credentials")
    client = _auth_client()

    # Factor 1: password
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        raise generic from None
    user = getattr(resp, "user", None)
    if not user:
        raise generic

    # Must be an admin (authoritative app_metadata). Self-heal the allowlist.
    if not _is_admin_user(user):
        logger.warning(f"Admin login denied (not admin): {email}")
        raise generic
    grant_admin(user.id, email)

    # Don't keep the password-grade session around.
    try:
        client.auth.sign_out()
    except Exception as e:
        logger.debug(f"Best-effort sign_out failed (ignored): {e}")

    # Factor 2: email OTP. Falls back to direct Resend generation/dispatch if Supabase mailer fails.
    # Returns a handle regardless so the response shape can't be used to probe accounts.
    try:
        client.auth.sign_in_with_otp({"email": email, "options": {"should_create_user": False}})
    except Exception as e:
        logger.warning(f"Supabase sign_in_with_otp failed for {email} ({e}); attempting direct Resend fallback")
        otp, action_link = _generate_otp_link(email)
        if otp:
            sent = _send_otp_via_resend(email, otp, action_link)
            if not sent:
                logger.error(f"Failed to deliver admin OTP to {email} via Resend fallback")
        else:
            logger.error(f"Failed to generate admin OTP link for {email}")

    handle = secrets.token_urlsafe(32)
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", ADMIN_PREAUTH_TTL, email)
    return handle


def _render_otp_email_html(otp: str, action_link: str | None = None) -> str:
    template_path = Path(__file__).resolve().parent.parent / "supabase" / "templates" / "magic_link.html"
    if template_path.exists():
        try:
            html = template_path.read_text(encoding="utf-8")
            html = html.replace("{{ .Token }}", otp)
            if action_link:
                html = html.replace("{{ .ConfirmationURL }}", action_link)
                html = html.replace("{{ if .ConfirmationURL }}", "").replace("{{ end }}", "")
            else:
                html = re.sub(r"\{\{\s*if\s*\.ConfirmationURL\s*\}\}.*?\{\{\s*end\s*\}\}", "", html, flags=re.DOTALL)
            return html
        except Exception as e:
            logger.warning(f"Failed to read email template {template_path}: {e}")

    return (
        f"<h2>Your Nego-lah Verification Code</h2>"
        f"<p>Use the following one-time code to sign in:</p>"
        f"<h1 style='letter-spacing: 4px; font-family: monospace;'>{otp}</h1>"
        f"<p>Valid for 10 minutes. Do not share this code.</p>"
    )


def _generate_otp_link(email: str) -> tuple[str | None, str | None]:
    """Generate an OTP token using Supabase admin service role."""
    try:
        res = admin_supabase.auth.admin.generate_link({"type": "magiclink", "email": email})
        otp = getattr(res.properties, "email_otp", None)
        action_link = getattr(res.properties, "action_link", None)
        return otp, action_link
    except Exception as e:
        logger.error(f"Failed to generate OTP link via admin_supabase: {e}")
        return None, None


def _send_otp_via_resend(email: str, otp: str, action_link: str | None = None) -> bool:
    """Fallback OTP delivery via Resend API when Supabase built-in mailer fails."""
    if not RESEND_API_KEY:
        return False

    html_content = _render_otp_email_html(otp, action_link)
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    senders = []
    if RESEND_FORWARD_FROM:
        senders.append(RESEND_FORWARD_FROM)
    senders.append("Nego-lah <onboarding@resend.dev>")

    seen = set()
    unique_senders = [s for s in senders if s and not (s in seen or seen.add(s))]

    for sender in unique_senders:
        payload = {
            "from": sender,
            "to": [email],
            "subject": f"Your Nego-lah Verification Code: {otp}",
            "html": html_content,
        }
        try:
            with httpx.Client(timeout=10.0) as http_client:
                resp = http_client.post("https://api.resend.com/emails", headers=headers, json=payload)
                if resp.status_code < 300:
                    logger.info(f"Admin OTP delivered to {email} via Resend fallback (sender: {sender})")
                    return True
                logger.warning(f"Resend send attempt from {sender} returned {resp.status_code}: {resp.text}")
        except Exception as err:
            logger.warning(f"Resend send attempt from {sender} failed: {err}")

    return False


# ---------------------------------------------------------------------------
# Factor 2: OTP verification  ->  admin session
# ---------------------------------------------------------------------------

def verify_otp_and_open_session(handle: str, code: str, response: Response, request: Request) -> dict:
    """Validate the OTP against the pre-auth handle and open an admin session."""
    generic = HTTPException(status_code=401, detail="Invalid or expired code")

    email = redis_client.get(f"{_PREAUTH_KEY}{handle}")
    if not email:
        raise generic
    enforce_otp_rate_limit(handle)

    client = _auth_client()
    try:
        resp = client.auth.verify_otp({"email": email, "token": code, "type": "email"})
    except Exception:
        raise generic from None
    user = getattr(resp, "user", None)
    if not user or not _is_admin_user(user):
        raise generic

    # One-time handle: consume it.
    redis_client.delete(f"{_PREAUTH_KEY}{handle}")
    grant_admin(user.id, email)
    try:
        client.auth.sign_out()
    except Exception as e:
        logger.debug(f"Best-effort sign_out failed (ignored): {e}")

    sid = _create_session(user.id, email)
    _set_cookie(response, sid)

    # CSRF: generate a token for this session and set the readable cookie.
    csrf_token = generate_csrf_token(sid)
    set_csrf_cookie(response, csrf_token)

    write_audit(user.id, email, "login", None, client_ip(request))
    return {"user_id": user.id, "email": email}


# ---------------------------------------------------------------------------
# Opaque session store
# ---------------------------------------------------------------------------

def _create_session(user_id: str, email: str) -> str:
    sid = secrets.token_urlsafe(32)
    redis_client.setex(
        f"{_SESS_KEY}{sid}",
        ADMIN_SESSION_TTL,
        json.dumps({"user_id": user_id, "email": email}),
    )
    return sid


def _set_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=sid,
        max_age=ADMIN_SESSION_TTL,
        httponly=True,
        secure=ADMIN_COOKIE_SECURE,
        samesite=ADMIN_COOKIE_SAMESITE,
        path=ADMIN_COOKIE_PATH,
        domain=ADMIN_COOKIE_DOMAIN,
    )


def clear_session(request: Request, response: Response) -> None:
    sid = request.cookies.get(ADMIN_COOKIE_NAME)
    if sid:
        redis_client.delete(f"{_SESS_KEY}{sid}")
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path=ADMIN_COOKIE_PATH, domain=ADMIN_COOKIE_DOMAIN)

    # Also clear the CSRF token and its cookie.
    clear_csrf(sid, response)


# ---------------------------------------------------------------------------
# Per-request dependency
# ---------------------------------------------------------------------------

async def verify_admin(request: Request) -> dict:
    """
    Gate EVERY admin data route. Validates the opaque session cookie against
    Redis, confirms the user is still on the admin allowlist (instant revoke),
    and slides the session TTL forward.
    """
    unauth = HTTPException(status_code=401, detail="Not authenticated")
    sid = request.cookies.get(ADMIN_COOKIE_NAME)
    if not sid:
        raise unauth

    raw = redis_client.get(f"{_SESS_KEY}{sid}")
    if not raw:
        raise unauth
    try:
        data = json.loads(raw)
    except Exception:
        raise unauth from None

    user_id = data.get("user_id")
    if not user_id or not is_allowed_admin(user_id):
        # Revoked (or allowlist lost) — kill the session.
        redis_client.delete(f"{_SESS_KEY}{sid}")
        raise unauth

    # Sliding expiration.
    redis_client.expire(f"{_SESS_KEY}{sid}", ADMIN_SESSION_TTL)
    data["ip"] = client_ip(request)
    return data


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def write_audit(actor_user_id: str, actor_email: str, action: str,
                target: str | None, ip: str) -> None:
    try:
        admin_supabase.table("admin_audit_log").insert({
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "action": action,
            "target": target,
            "ip": ip,
        }).execute()
    except Exception as e:
        # Never let audit failures break the action; just log it.
        logger.error(f"Failed to write admin audit log ({action}): {e}")
