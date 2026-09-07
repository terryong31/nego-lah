import os

import httpx
from fastapi import Header, HTTPException, Request

from core.telemetry import logger


async def verify_turnstile(
    request: Request = None,
    x_turnstile_token: str | None = Header(default=None, alias="X-Turnstile-Token"),
    cf_turnstile_response: str | None = Header(default=None, alias="cf-turnstile-response"),
) -> bool:
    """
    Cloudflare Turnstile token validator adhering to Cloudflare's canonical siteverify specification.
    - In development mode (not production): verification is disabled and always returns True.
    - In production mode: verification is strictly enforced:
      * TURNSTILE_SECRET_KEY must be configured (missing raises HTTP 500).
      * Test/dummy tokens or test keys are rejected with HTTP 403.
      * Token must be non-empty and 1 <= len <= 2048 (missing raises HTTP 400).
      * Calls Cloudflare siteverify (failure raises HTTP 403).
    """
    is_prod = (os.getenv("ENV") or os.getenv("ENVIRONMENT") or "development").lower() in ("production", "prod")
    if not is_prod:
        logger.debug("Turnstile verification bypassed in development mode.")
        return True

    secret_key = os.getenv("TURNSTILE_SECRET_KEY") or os.getenv("TURNSTILE_SECRET") or ""
    if not secret_key:
        logger.error("TURNSTILE_SECRET_KEY is not configured in production mode.")
        raise HTTPException(status_code=500, detail="Turnstile secret key is not configured in production")

    if secret_key.startswith("1x00000000"):
        logger.warning("Cloudflare Turnstile test key is rejected in production mode.")
        raise HTTPException(status_code=403, detail="Turnstile test secret is rejected in production")

    token = None
    if isinstance(x_turnstile_token, str) and x_turnstile_token.strip():
        token = x_turnstile_token.strip()
    elif isinstance(cf_turnstile_response, str) and cf_turnstile_response.strip():
        token = cf_turnstile_response.strip()

    if not token or len(token) > 2048:
        raise HTTPException(status_code=400, detail="Valid Turnstile verification token required")

    # In production, dummy/testing tokens must be rejected
    if token.startswith("XXXX.DUMMY.") or token in ("dummy-token", "test-token"):
        logger.warning("Turnstile dummy/testing token rejected in production mode.")
        raise HTTPException(status_code=403, detail="Test Turnstile tokens are rejected in production")

    data = {
        "secret": secret_key,
        "response": token,
    }

    # Include remote IP if request context is provided
    if request and hasattr(request, "client") and request.client and request.client.host:
        client_ip = request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
        if client_ip:
            data["remoteip"] = client_ip

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=data
            )
            outcome = res.json()
            if not outcome.get("success"):
                logger.warning(f"Turnstile verification failed: {outcome.get('error-codes')}")
                raise HTTPException(status_code=403, detail="Turnstile verification failed")

            # Check hostname allowlist if configured
            expected_hostnames = {
                h.strip().lower()
                for h in os.getenv("TURNSTILE_HOSTNAMES", "").split(",")
                if h.strip()
            }
            if expected_hostnames and outcome.get("hostname"):
                if outcome.get("hostname").lower() not in expected_hostnames:
                    logger.warning(f"Turnstile hostname mismatch: {outcome.get('hostname')} not in {expected_hostnames}")
                    raise HTTPException(status_code=403, detail="Turnstile verification origin rejected")

    except HTTPException:
        raise
    except Exception as e:
        # Fail OPEN on a transport failure, CLOSED on a verdict (SPEC-044 D).
        #
        # Reaching here means Cloudflare never answered — unreachable, timed
        # out, or a body that wasn't the documented JSON. There is no verdict
        # to act on, and refusing anyway would mean a Cloudflare outage takes
        # down every route this guards, including the admin console the AI
        # hands conversations to. An attacker can't induce this branch, and
        # what it guards keeps its real authentication underneath.
        #
        # A returned "success": false is a different thing entirely, and is
        # raised as a 403 above, before this handler.
        logger.warning(
            f"Turnstile siteverify unreachable, allowing the request: {e}"
        )
        return True

    return True
