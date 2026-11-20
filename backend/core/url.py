"""URL validation helpers shared across domains (SPEC-116 / SEC-19)."""

from urllib.parse import urlsplit


def is_safe_http_url(value: str | None) -> bool:
    """Return True only for absolute http(s) URLs with a host and no control chars."""
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    if not cleaned or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return False
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc) and bool(parsed.hostname)
