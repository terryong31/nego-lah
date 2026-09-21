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


class IPRateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Healthcheck probe exemption
        if path == "/health":
            await self.app(scope, receive, send)
            return

        client_ip = get_client_ip(scope)
        allowed, retry_after = await asyncio.to_thread(check_ip_rate_limit, path, client_ip)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Too many requests."},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
