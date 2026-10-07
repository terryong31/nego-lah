"""SPEC-104 / ADR-0032 — the origin trusts our zone, not Cloudflare at large.

Cloudflare's IP ranges are shared by every tenant, so "the peer is a Cloudflare
address" proves nothing about which zone's rules ran. Caddy therefore (a) only
takes the client IP from `CF-Connecting-IP` when the peer is Cloudflare, and
overwrites the upstream header with that value so a caller cannot choose its own
rate-limit key; and (b) rejects requests without the secret header our zone's
Transform Rule adds.

The behaviour was verified against `caddy:2.7` in Docker; these are config
tests that keep the manifest from drifting away from it.
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CADDYFILE = (REPO_ROOT / "Caddyfile").read_text()


def _site_block() -> str:
    start = CADDYFILE.index("api.negolah.my {")
    return CADDYFILE[start:]


def _global_block() -> str:
    return CADDYFILE[: CADDYFILE.index("api.negolah.my {")]


class TestClientIp:
    def test_trusted_proxies_are_global_so_client_ip_resolution_uses_them(self):
        assert re.search(r"servers\s*\{[^}]*trusted_proxies static 173\.245\.48\.0/20", _global_block(), re.S)

    def test_client_ip_comes_from_cf_connecting_ip_only_via_trusted_peers(self):
        assert re.search(r"client_ip_headers\s+CF-Connecting-IP", _global_block())

    def test_upstream_header_is_overwritten_with_the_resolved_client_ip(self):
        assert re.search(r"header_up\s+CF-Connecting-IP\s+\{client_ip\}", _site_block())


class TestOriginAuth:
    def test_requests_without_the_zone_secret_are_refused(self):
        site = _site_block()
        matcher = re.search(r"@(\w+)\s+expression\s+`([^`]*)`", site)
        assert matcher, "origin-auth matcher missing"
        name, expr = matcher.groups()
        assert "{http.request.header.X-Origin-Auth}" in expr
        assert "{env.ORIGIN_AUTH_SECRET}" in expr
        # Inert while unset, so a merge cannot lock production out before the rule exists.
        assert '{env.ORIGIN_AUTH_SECRET} != ""' in expr
        assert re.search(rf"respond\s+@{name}\b[^\n]*403", site)

    def test_the_secret_never_reaches_the_backend(self):
        assert re.search(r"header_up\s+-X-Origin-Auth", _site_block())

    def test_secret_is_not_written_into_the_caddyfile(self):
        assert "{$ORIGIN_AUTH_SECRET" not in CADDYFILE


class TestSecretDelivery:
    @pytest.fixture(scope="class")
    def caddy(self):
        return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())["services"]["caddy"]

    def test_caddy_gets_its_own_env_file_not_the_backends(self, caddy):
        assert caddy.get("env_file") == ["./caddy.env"]

    def test_deploy_writes_caddy_env_from_the_one_key(self):
        workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text())
        steps = workflow["jobs"]["deploy-backend"]["steps"]
        script = next(s["with"]["script"] for s in steps if "script" in s.get("with", {}))
        assert re.search(r"grep -E '\^ORIGIN_AUTH_SECRET=' backend/\.env > caddy\.env", script)
        assert "chmod 600 caddy.env" in script
        # It must exist before compose reads it.
        assert script.index("caddy.env") < script.index("docker compose up")


def test_deploy_disarms_the_origin_check_if_the_zone_is_not_sending_the_secret():
    """ADR-0032 ordering guard: a secret in Infisical with no Transform Rule at
    Cloudflare would refuse every request. The deploy checks through the edge and,
    on a 403, empties caddy.env, recreates Caddy and fails red."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    script = next(s["with"]["script"] for s in steps if "script" in s.get("with", {}))
    guard = script[script.index("https://api.negolah.my/health") :]
    assert '"403"' in guard
    assert ": > caddy.env" in guard
    assert "--force-recreate caddy" in guard
    assert "exit 1" in guard
