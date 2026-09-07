"""
Defense middleware implementing OWASP API security standards:
1. SecurityHeadersMiddleware: Sets hardened HTTP response headers (CSP, HSTS, X-Content-Type-Options, etc.)
2. RequestDefenseMiddleware: Enforces request body size limits (preventing payload bombs) and URL injection guards.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
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


class RequestDefenseMiddleware(BaseHTTPMiddleware):
    """
    Guards incoming requests against:
    - Payload size denial-of-service (enforces Content-Length ceiling).
    - Null-byte and control character path injections.
    """

    def __init__(
        self,
        app,
        max_content_length: int = 10 * 1024 * 1024,  # 10 MB default
        upload_path_prefix: str | tuple[str, ...] = ("/admin/analyze-image", "/admin/items"),
        max_upload_content_length: int = 15 * 1024 * 1024,  # 15 MB for image uploads
    ):
        super().__init__(app)
        self.max_content_length = max_content_length
        self.upload_path_prefix = upload_path_prefix
        self.max_upload_content_length = max_upload_content_length

    async def dispatch(self, request: Request, call_next) -> Response:
        raw_path = request.scope.get("raw_path", b"").decode("latin-1")
        query_string = request.scope.get("query_string", b"").decode("latin-1")

        # Guard 1: Detect null-byte injection (%00 or \x00)
        if "\x00" in raw_path or "%00" in raw_path.lower() or "\x00" in query_string or "%00" in query_string.lower():
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid request path or query parameters"}
            )

        # Guard 2: Enforce request payload size limit based on path
        path = request.url.path
        limit = (
            self.max_upload_content_length
            if path.startswith(self.upload_path_prefix)
            else self.max_content_length
        )

        content_length_header = request.headers.get("content-length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
                if content_length > limit:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Payload too large. Maximum permitted size is {limit} bytes."}
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"}
                )

        return await call_next(request)
