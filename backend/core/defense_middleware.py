"""
Defense middleware implementing OWASP API security standards:
1. SecurityHeadersMiddleware: Sets hardened HTTP response headers (CSP, HSTS, X-Content-Type-Options, etc.)
2. RequestDefenseMiddleware: Enforces request body size limits (preventing payload bombs) and URL injection guards.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to every outgoing HTTP response adhering to OWASP recommendations.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Mitigate MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent framing / clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Modern standard disables obsolete buggy browser XSS filters in favor of CSP
        response.headers["X-XSS-Protection"] = "0"

        # Strict referrer leakage prevention
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Restrict hardware sensors & browser features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # Restrictive Content Security Policy for API payloads
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; sandbox"

        # Prevent Adobe Flash / PDF cross-domain policy leakage
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        # Strict-Transport-Security (HSTS) in production
        is_prod = (
            os.getenv("ENV", "development").lower() in ("production", "prod")
            or os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod")
        )
        if is_prod:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response


class RequestDefenseMiddleware:
    """
    Guards incoming requests against:
    - Payload size denial-of-service (a declared *and* an actual byte ceiling).
    - Null-byte and control character path injections.

    Written as a raw ASGI middleware rather than a `BaseHTTPMiddleware`, because
    the size guard has to sit on the `receive` channel itself. `BaseHTTPMiddleware`
    only hands you a finished `Request`, which is one abstraction too high: by the
    time you can see how many bytes arrived, they have already arrived.
    """

    def __init__(
        self,
        app,
        max_content_length: int = 10 * 1024 * 1024,  # 10 MB default
        upload_path_prefix: str | tuple[str, ...] = ("/admin/analyze-image", "/admin/items"),
        max_upload_content_length: int = 15 * 1024 * 1024,  # 15 MB for image uploads
    ):
        self.app = app
        self.max_content_length = max_content_length
        self.upload_path_prefix = upload_path_prefix
        self.max_upload_content_length = max_upload_content_length

    def _limit_for(self, path: str) -> int:
        return (
            self.max_upload_content_length
            if path.startswith(self.upload_path_prefix)
            else self.max_content_length
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_path = scope.get("raw_path", b"").decode("latin-1")
        query_string = scope.get("query_string", b"").decode("latin-1")

        # Guard 1: Detect null-byte injection (%00 or \x00)
        if "\x00" in raw_path or "%00" in raw_path.lower() or "\x00" in query_string or "%00" in query_string.lower():
            await JSONResponse(
                status_code=400,
                content={"detail": "Invalid request path or query parameters"},
            )(scope, receive, send)
            return

        request = Request(scope, receive)
        limit = self._limit_for(request.url.path)
        too_large = JSONResponse(
            status_code=413,
            content={"detail": f"Payload too large. Maximum permitted size is {limit} bytes."},
        )

        # Guard 2a: refuse on the *declared* size, before a single byte is read.
        content_length_header = request.headers.get("content-length")
        if content_length_header:
            try:
                if int(content_length_header) > limit:
                    await too_large(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )(scope, receive, send)
                return

        # Guard 2b: and on the *actual* size, counted as it streams in.
        #
        # A header check alone protects nothing. `Transfer-Encoding: chunked`
        # carries no Content-Length at all, and a Content-Length can simply be a
        # lie — in both cases the header guard waves the request through and the
        # endpoint's own `await request.body()` buffers however much the attacker
        # feels like sending. On a 1.2 GB box that is an OOM, not a slow request.
        #
        # So the body is metered on the way past. Once the ceiling is crossed the
        # reader is told the peer went away, which is what `http.disconnect`
        # means on this channel and what Starlette turns into `ClientDisconnect`.
        # We catch that below and answer 413 instead — the handler never sees a
        # truncated body it might mistake for a complete one, and it never gets
        # the remaining bytes to hold in memory either.
        state = {"received": 0, "over_limit": False}

        async def metered_receive():
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > limit:
                    state["over_limit"] = True
                    return {"type": "http.disconnect"}
            return message

        response_started = False

        async def guarded_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, metered_receive, guarded_send)
        except ClientDisconnect:
            # A real disconnect is the client's business and stays an error;
            # only the one we manufactured becomes a 413.
            if not state["over_limit"]:
                raise
            if not response_started:
                await too_large(scope, receive, send)
            return

        # A route that answers without ever reading the oversized body has not
        # been attacked — but if it read part of it and then answered, we still
        # let its response stand; the bytes are already spent and second-guessing
        # a handler that decided it had enough would break streaming endpoints.
        if state["over_limit"] and not response_started:
            await too_large(scope, receive, send)
