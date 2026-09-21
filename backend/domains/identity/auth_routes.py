"""
Buyer authentication. The backend talks to Supabase; the browser gets a cookie.

Every route here used to be a `supabase.auth.*` call in the SPA, which is why the
buyer's access token had to be readable by JavaScript in the first place. Moving
the calls behind the API is what lets the session become an opaque id the page
cannot read (SPEC-093, ADR-0028).

Shapes worth knowing:
  * Success returns the *user*, never a token. If a response body here ever grows
    an `access_token`, the whole exercise is undone.
  * The email flows (confirm signup, recovery, email change) and the OAuth return
    all land on `GET /auth/callback`, which establishes the session server-side
    and then 302s into the SPA. The browser never holds the code.
  * Failures are deliberately vague on the login path and deliberately identical
    on the forgot-password path, so neither can be used to enumerate accounts.
"""

import json
import time
from urllib.parse import quote_plus, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from core.connector import new_user_client
from core.csrf import USER_SCOPE, generate_csrf_token, set_csrf_cookie, verify_user_csrf_token
from core.env import (
    API_BASE_URL,
    FRONTEND_URL,
    SUPABASE_URL,
    USER_COOKIE_NAME,
    USER_PKCE_COOKIE_NAME,
)
from core.logger import logger
from core.schemas import AuthCredentialsRequest, AuthEmailRequest, AuthPasswordResetRequest
from core.security import verify_turnstile
from domains.identity.auth_middleware import verify_user_token
from domains.identity.user_session import (
    clear_pkce_cookie,
    clear_session_cookies,
    new_pkce_pair,
    open_session_for,
    read_session,
    set_pkce_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_CALLBACK_URL = f"{API_BASE_URL}/auth/callback"


def _safe_next(value: str | None) -> str:
    """A post-auth landing path, restricted to this app.

    The value reaches us from a query string, so an absolute or protocol-relative
    URL here would turn every auth route into an open redirect — mirrors
    `safeRedirectPath` on the frontend.
    """
    if not value or not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        return "/"
    return value


# Where each kind of link should put the visitor once the session is open. An
# email link has no `next` (nothing started it in this browser), so without this
# every confirmation would silently land on the homepage and leave the person
# wondering whether it worked.
_EMAIL_LINK_LANDINGS = {
    "recovery": "/reset-password",
    "signup": "/confirm?status=confirmed",
    "invite": "/confirm?status=confirmed",
    "email_change": "/profile?status=email_updated",
}


def _landing_for(link_type: str | None, stored_next: str | None) -> str:
    """The SPA path to 302 to after a successful callback."""
    if link_type in _EMAIL_LINK_LANDINGS:
        return _EMAIL_LINK_LANDINGS[link_type]
    return _safe_next(stored_next)


def _user_payload(user) -> dict:
    """The subset of the Supabase user the SPA actually renders."""
    return {
        "id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "user_metadata": getattr(user, "user_metadata", None) or {},
    }


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------


@router.post("/login", dependencies=[Depends(verify_turnstile)])
def login(payload: AuthCredentialsRequest, response: Response):
    """Exchange credentials for a session cookie.

    Turnstile-gated for the same reason admin login is: this is an
    unauthenticated credential endpoint, and the per-IP limiter alone does not
    make one cheap to grind.
    """
    client = new_user_client()
    try:
        result = client.auth.sign_in_with_password(
            {"email": payload.email.strip().lower(), "password": payload.password}
        )
    except Exception:
        # One message for wrong password, unknown address and unconfirmed
        # account alike — the three are not distinguishable from outside.
        raise HTTPException(status_code=401, detail="Invalid email or password") from None

    session = getattr(result, "session", None)
    if not session or not getattr(session, "access_token", None):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    open_session_for(response, session)
    return {"user": _user_payload(session.user)}


@router.post("/register", dependencies=[Depends(verify_turnstile)])
def register(payload: AuthCredentialsRequest):
    """Create an account. Confirmation happens through the emailed link.

    No session is opened here even when Supabase returns one (it does when email
    confirmation is disabled): sign-in is `/auth/login`'s job, and keeping the
    two apart means there is exactly one place that mints a cookie.
    """
    client = new_user_client()
    try:
        client.auth.sign_up(
            {
                "email": payload.email.strip().lower(),
                "password": payload.password,
                "options": {"email_redirect_to": _CALLBACK_URL},
            }
        )
    except Exception as e:
        message = str(e).lower()
        if "already" in message or "registered" in message:
            # Supabase itself is ambiguous here by design; stay ambiguous.
            return {"confirmation_sent": True}
        logger.warning(f"Sign-up failed: {e}")
        raise HTTPException(status_code=400, detail="Could not create that account") from None

    return {"confirmation_sent": True}


@router.post("/logout", dependencies=[Depends(verify_user_csrf_token)])
def logout(request: Request, response: Response):
    """End the session. Safe to call without one."""
    clear_session_cookies(request, response)
    return {"message": "Logged out"}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@router.get("/session")
def session(request: Request, response: Response):
    """Who the cookie belongs to. The SPA's boot call and its route guard.

    Also re-issues the CSRF cookie, which has a shorter life in practice than the
    session: a browser that dropped it (private-mode eviction, a clear-on-exit
    setting) would otherwise be authenticated but unable to POST anything.
    """
    sid = request.cookies.get(USER_COOKIE_NAME, "")
    stored = read_session(sid) if sid else None
    if not stored:
        raise HTTPException(status_code=401, detail="No session")

    client = new_user_client()
    try:
        user_response = client.auth.get_user(stored["access_token"])
        user = getattr(user_response, "user", None)
    except Exception:
        user = None

    if not user:
        raise HTTPException(status_code=401, detail="No session")

    set_csrf_cookie(response, generate_csrf_token(sid, USER_SCOPE), USER_SCOPE)
    return {"user": _user_payload(user)}


# ---------------------------------------------------------------------------
# OAuth (PKCE, brokered server-side)
# ---------------------------------------------------------------------------


@router.get("/oauth/start")
def oauth_start(response: Response, provider: str = "google", next: str = "/"):
    """Begin an OAuth sign-in.

    We build the authorize URL and own the PKCE verifier ourselves rather than
    calling `sign_in_with_oauth`, because the SDK stores the verifier in the
    client's own storage — and this client is a throwaway that will not exist by
    the time the callback arrives.
    """
    if provider not in ("google",):
        raise HTTPException(status_code=400, detail="Unsupported provider")

    verifier, challenge = new_pkce_pair()
    query = urlencode(
        {
            "provider": provider,
            "redirect_to": _CALLBACK_URL,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        }
    )
    redirect = RedirectResponse(url=f"{SUPABASE_URL}/auth/v1/authorize?{query}", status_code=302)
    set_pkce_cookie(redirect, verifier, _safe_next(next))
    return redirect


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    token_hash: str | None = None,
    type: str | None = None,
    error_description: str | None = None,
):
    """Where every Supabase redirect lands: OAuth, signup confirm, recovery, email change.

    Two shapes arrive here. `?code=` is the PKCE authorization code from an OAuth
    round trip, redeemable only with the verifier in the cookie we set at
    `/oauth/start`. `?token_hash=&type=` is what the email templates carry. Both
    end the same way — a session on the server, a cookie on the browser, and a
    302 into the SPA with nothing sensitive in the URL.
    """
    verifier = None
    stored_next = None
    raw_pkce = request.cookies.get(USER_PKCE_COOKIE_NAME)
    if raw_pkce:
        try:
            parsed = json.loads(raw_pkce)
            verifier, stored_next = parsed.get("v"), parsed.get("r")
        except (TypeError, ValueError):
            verifier, stored_next = None, None

    def _leave(path: str, session=None) -> RedirectResponse:
        """One exit: 302 into the SPA, session attached if we have one, verifier
        expired either way — it is single-use by construction."""
        redirect = RedirectResponse(url=f"{FRONTEND_URL}{path}", status_code=302)
        if session is not None:
            open_session_for(redirect, session)
        clear_pkce_cookie(redirect)
        return redirect

    if error_description:
        return _leave(f"/login?error={quote_plus(error_description)}")

    client = new_user_client()
    supabase_session = None

    try:
        if code:
            if not verifier:
                # No verifier means this code did not start here. Refusing is the
                # whole point of PKCE.
                raise ValueError("Missing PKCE verifier")
            result = client.auth.exchange_code_for_session(
                {"auth_code": code, "code_verifier": verifier, "redirect_to": _CALLBACK_URL}
            )
            supabase_session = getattr(result, "session", None)
        elif token_hash and type:
            result = client.auth.verify_otp({"token_hash": token_hash, "type": type})
            supabase_session = getattr(result, "session", None)
    except Exception as e:
        logger.info(f"Auth callback rejected: {e}")
        supabase_session = None

    if not supabase_session or not getattr(supabase_session, "access_token", None):
        return _leave("/login?error=link_invalid")

    return _leave(_landing_for(type, stored_next), supabase_session)


# ---------------------------------------------------------------------------
# Password recovery
# ---------------------------------------------------------------------------


@router.post("/password/forgot", dependencies=[Depends(verify_turnstile)])
def password_forgot(payload: AuthEmailRequest):
    """Send a recovery link. Always reports success.

    Whether the address has an account is not this endpoint's to disclose, so the
    response and its timing do not vary.
    """
    client = new_user_client()
    try:
        client.auth.reset_password_email(
            payload.email.strip().lower(),
            {"redirect_to": _CALLBACK_URL},
        )
    except Exception as e:
        logger.info(f"Password reset request not delivered: {e}")

    return {"sent": True}


@router.post("/password/reset", dependencies=[Depends(verify_user_csrf_token)])
def password_reset(payload: AuthPasswordResetRequest, request: Request, user_id: str = Depends(verify_user_token)):
    """Set a new password, using the recovery session the callback established.

    This is the one password change that does not ask for the current one — the
    emailed link is the factor. `PUT /user/{id}/password` remains the path for a
    signed-in change and still costs the old password (SPEC-056 #3).
    """
    sid = request.cookies.get(USER_COOKIE_NAME, "")
    stored = read_session(sid) if sid else None
    if not stored:
        raise HTTPException(status_code=401, detail="No recovery session")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    client = new_user_client()
    try:
        client.auth.set_session(stored["access_token"], stored["refresh_token"])
        client.auth.update_user({"password": payload.new_password})
    except Exception as e:
        logger.warning(f"Password reset failed for {user_id}: {e}")
        raise HTTPException(status_code=400, detail="Could not update the password") from None
    finally:
        try:
            client.auth.sign_out()
        except Exception as e:
            logger.debug(f"Best-effort sign_out failed (ignored): {e}")

    return {"updated": True, "at": int(time.time())}
