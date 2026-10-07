"""
Client IP resolution for Nego-Lah.

Behind Cloudflare and Caddy:
- Caddy resolves the client IP itself — from `CF-Connecting-IP` only when the
  peer is a Cloudflare edge, otherwise the peer address — and overwrites the
  upstream `CF-Connecting-IP` with it (SPEC-104). The backend is reachable only
  through Caddy, so the header it sees here is Caddy's, never the caller's.
- In local development, testing, or direct connections, fallback to `request.client.host`
  or ASGI `scope["client"][0]`.
- Reading raw `X-Forwarded-For` without trusted-proxy validation is dangerous because
  untrusted clients can inject arbitrary IPs into the header.
"""

from typing import Any


def get_client_ip(scope_or_request: Any) -> str:
    """Extract authoritative client IP from a FastAPI/Starlette Request or raw ASGI HTTP scope."""
    if hasattr(scope_or_request, "headers"):
        # FastAPI / Starlette Request or SimpleNamespace stand-in
        headers = scope_or_request.headers
        cf_ip = headers.get("cf-connecting-ip") or headers.get("CF-Connecting-IP")
        if cf_ip and isinstance(cf_ip, str) and cf_ip.strip():
            return cf_ip.strip()

        client = getattr(scope_or_request, "client", None)
        if client and hasattr(client, "host") and client.host:
            return client.host
        return "unknown"

    if isinstance(scope_or_request, dict):
        # Raw ASGI scope
        raw_headers = scope_or_request.get("headers", [])
        for k, v in raw_headers:
            name = k.decode("latin-1").lower() if isinstance(k, bytes) else str(k).lower()
            if name == "cf-connecting-ip":
                val = v.decode("latin-1").strip() if isinstance(v, bytes) else str(v).strip()
                if val:
                    return val

        client = scope_or_request.get("client")
        if client and isinstance(client, (tuple, list)) and len(client) > 0 and client[0]:
            return str(client[0])
        return "unknown"

    return "unknown"
