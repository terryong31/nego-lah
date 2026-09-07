"""Whose IP is it? — trusted-proxy handling for every IP-keyed limit.

Two bugs with one root cause, both found while load/security testing SPEC-043
before a conference:

1. **Every per-IP limit was one global bucket.** Caddy runs as a separate
   container, so it reaches the app from the docker bridge, not `127.0.0.1` —
   which is uvicorn's default `--forwarded-allow-ips`. Untrusted peer means
   `X-Forwarded-For` is ignored and `request.client.host` stays Caddy's own
   address, identical for every request on earth. The SPEC-043 per-IP ceilings
   would then have been shared by the entire room: one attendee refreshing the
   catalog could 429 everyone else.

2. **The admin login limiter could be bypassed with a header.** `client_ip()`
   read the *first* `X-Forwarded-For` value with no trust check. Caddy appends
   to whatever the client sent, so the first value is attacker-controlled:
   rotate it and the `adminlogin:{email}:{ip}` bucket is fresh every attempt.
   It also forged the IP written into the audit log.

The fix has two halves and needs both: uvicorn must trust the bridge so it
resolves the real client, and `client_ip()` must stop parsing the header
itself and use what uvicorn resolved.
"""

import os
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_session import client_ip  # noqa: E402

DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


# ---------------------------------------------------------------------------
# Half one: uvicorn is told which peers may speak for someone else
# ---------------------------------------------------------------------------

def test_uvicorn_trusts_the_reverse_proxy_for_forwarded_headers():
    cmd = DOCKERFILE.read_text()
    assert "--forwarded-allow-ips" in cmd, (
        "without this uvicorn ignores X-Forwarded-For from the Caddy container "
        "and every request shares one rate-limit bucket"
    )


def test_the_proxy_trust_list_is_not_a_wildcard():
    """`*` would be worse than the bug it fixes.

    With `always_trust`, uvicorn takes the *first* X-Forwarded-For entry. Caddy
    appends to the client's own header, so that first entry is whatever the
    client typed — letting anyone pick their own rate-limit bucket, or poison
    somebody else's. Naming the bridge range instead makes uvicorn walk the
    list from the right and stop at the first address a proxy didn't add.
    """
    cmd = DOCKERFILE.read_text()
    match = re.search(r"--forwarded-allow-ips[= ]+['\"]?([^'\"\s]+)", cmd)
    assert match, "could not read the configured trust list"
    assert match.group(1) != "*", (
        "a wildcard trust list makes the client's own header authoritative"
    )


def test_the_trust_list_covers_the_docker_bridge_range():
    cmd = DOCKERFILE.read_text()
    assert "172.16.0.0/12" in cmd, (
        "compose puts container networks in 172.16.0.0/12; Caddy has to be in "
        "the trust list or its X-Forwarded-For is discarded"
    )


# ---------------------------------------------------------------------------
# Half two: client_ip trusts uvicorn's answer, not the raw header
# ---------------------------------------------------------------------------

def _request(headers: dict, peer: str | None = "203.0.113.9"):
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=peer) if peer else None,
    )


def test_client_ip_uses_the_resolved_peer():
    assert client_ip(_request({}, peer="198.51.100.4")) == "198.51.100.4"


def test_a_forged_forwarded_header_cannot_change_the_bucket():
    """The attack: send your own X-Forwarded-For and get a clean login-attempt
    budget for every value you invent."""
    forged = _request(
        {"X-Forwarded-For": "1.2.3.4"},
        peer="203.0.113.9",
    )

    assert client_ip(forged) == "203.0.113.9", (
        "the header won over the real peer — the admin login limiter is "
        "bypassable by rotating one header value"
    )


def test_rotating_the_forged_header_keeps_hitting_the_same_bucket():
    seen = {
        client_ip(_request({"X-Forwarded-For": f"10.0.0.{i}"}, peer="203.0.113.9"))
        for i in range(10)
    }
    assert seen == {"203.0.113.9"}


def test_client_ip_falls_back_when_there_is_no_peer():
    assert client_ip(_request({}, peer=None)) == "unknown"


@pytest.mark.parametrize("header", ["X-Forwarded-For", "x-forwarded-for", "X-Real-IP"])
def test_no_client_supplied_header_is_consulted(header):
    assert client_ip(_request({header: "9.9.9.9"}, peer="203.0.113.9")) == "203.0.113.9"
