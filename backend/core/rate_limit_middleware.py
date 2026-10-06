"""
Pure ASGI Pre-Routing Rate Limit Middleware.

Runs BEFORE FastAPI routing and dependency execution (such as `verify_user_token`).
Blocks IP flood attacks and forged-token floods before invoking auth or hitting external services.
Written as raw ASGI (not BaseHTTPMiddleware) to avoid buffering Server-Sent Events (SSE).
"""

import asyncio

from fastapi.responses import JSONResponse

from core.ip import get_client_ip
from core.limiter import check_ip_rate_limit
from core.logger import logger


class IPRateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Health and readiness probe exemption
        if path in ("/health", "/ready"):
            await self.app(scope, receive, send)
            return

        client_ip = get_client_ip(scope)
        try:
            allowed, retry_after = await asyncio.to_thread(check_ip_rate_limit, path, client_ip)
        except Exception as e:
            # Fail open: this is a flood guard, not an auth check. A Redis error
            # here used to be a 500 on every route, storefront included (audit
            # REL-1); the session and CSRF checks behind it still fail closed.
            logger.warning(f"IP rate limiter unavailable, allowing request: {e}")
            allowed, retry_after = True, 0
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Too many requests."},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
