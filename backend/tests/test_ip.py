from types import SimpleNamespace

from core.ip import get_client_ip


def test_request_with_cf_connecting_ip():
    req = SimpleNamespace(
        headers={"CF-Connecting-IP": "198.51.100.42"},
        client=SimpleNamespace(host="172.16.0.2"),
    )
    assert get_client_ip(req) == "198.51.100.42"


def test_request_with_lowercase_cf_connecting_ip():
    req = SimpleNamespace(
        headers={"cf-connecting-ip": "198.51.100.43"},
        client=SimpleNamespace(host="172.16.0.2"),
    )
    assert get_client_ip(req) == "198.51.100.43"


def test_request_fallback_to_client_host():
    req = SimpleNamespace(
        headers={"X-Forwarded-For": "attacker.spoofed.ip"},
        client=SimpleNamespace(host="203.0.113.10"),
    )
    assert get_client_ip(req) == "203.0.113.10"


def test_request_unknown_client():
    req = SimpleNamespace(headers={}, client=None)
    assert get_client_ip(req) == "unknown"


def test_asgi_scope_with_cf_connecting_ip():
    scope = {
        "type": "http",
        "headers": [
            (b"host", b"api.negolah.my"),
            (b"cf-connecting-ip", b"203.0.113.88"),
        ],
        "client": ("172.16.0.3", 54321),
    }
    assert get_client_ip(scope) == "203.0.113.88"


def test_asgi_scope_fallback_to_client():
    scope = {
        "type": "http",
        "headers": [(b"host", b"api.negolah.my")],
        "client": ("198.51.100.99", 54321),
    }
    assert get_client_ip(scope) == "198.51.100.99"


def test_asgi_scope_unknown():
    scope = {"type": "http", "headers": []}
    assert get_client_ip(scope) == "unknown"
