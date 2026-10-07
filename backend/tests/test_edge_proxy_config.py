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

import os
import pathlib
import re
import shutil
import subprocess
from types import SimpleNamespace

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

    def test_refusals_are_marked_so_the_deploy_can_tell_them_from_cloudflares(self):
        """Cloudflare answers some requests itself (Bot Fight Mode, WAF) with a 403
        that never reached the origin. Only Caddy's own refusal carries the mark."""
        site = _site_block()
        name = re.search(r"@(\w+)\s+expression\s+`", site).group(1)
        assert re.search(rf'header\s+@{name}\s+X-Origin-Check\s+"refused\b', site)

    def test_the_mark_says_whether_the_header_was_absent_or_wrong(self):
        """Absent means the zone's rule is not running; wrong means it sends another
        value. The remedy differs, so the deploy log has to say which."""
        site = _site_block()
        mapping = re.search(r"map\s+\{http\.request\.header\.X-Origin-Auth\}\s+\{(\w+)\}\s*\{([^}]*)\}", site)
        assert mapping, "origin-auth reason map missing"
        output, body = mapping.groups()
        assert re.search(r'^\s*""\s+absent\s*$', body, re.M)
        assert re.search(r"^\s*default\s+mismatched\s*$", body, re.M)
        assert re.search(rf'X-Origin-Check\s+"refused; X-Origin-Auth \{{{output}\}}"', site)

    def test_the_mark_never_echoes_the_header_value(self):
        """On a mismatch the value Caddy received may be the zone's real secret."""
        for line in _site_block().splitlines():
            if "X-Origin-Check" in line:
                assert "{http.request.header" not in line, line

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
        script = _deploy_script()
        assert re.search(r"grep -E '\^ORIGIN_AUTH_SECRET=' backend/\.env > caddy\.env", script)
        assert "chmod 600 caddy.env" in script
        # It must exist before compose reads it.
        assert script.index("caddy.env") < script.index("docker compose up")


def _deploy_script() -> str:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    return next(s["with"]["script"] for s in steps if "script" in s.get("with", {}))


def test_every_compose_up_pins_the_backend_tag():
    """Compose falls back to `:latest`, which the deploy never pulls. An `up` without
    the tag recreates the backend from whatever `:latest` happens to be on the box; the
    2026-10-07 guard did exactly that through `caddy`'s depends_on."""
    ups = [line for line in _deploy_script().splitlines() if "docker compose up" in line]
    assert ups
    for line in ups:
        assert "BACKEND_IMAGE_TAG=" in line, line


_STUB_CURL = """#!/usr/bin/env bash
# Writes $STUB_HEADERS to the -D file and prints $STUB_CODE as curl's -w output.
while [ $# -gt 0 ]; do
  if [ "$1" = "-D" ]; then printf '%b' "$STUB_HEADERS" > "$2"; shift; fi
  shift
done
printf '%s' "$STUB_CODE"
"""

_STUB_SUDO = """#!/usr/bin/env bash
echo "$*" >> sudo.log
"""

_REFUSED_VIA_CLOUDFLARE = (
    "HTTP/2 403\r\nserver: cloudflare\r\ncf-ray: 8c9d0e1f2a3b4c5d-SIN\r\n"
    "x-origin-check: refused; X-Origin-Auth absent\r\n\r\n"
)


class TestOriginGuard:
    """ADR-0032 ordering guard: a secret in Infisical with no Transform Rule at
    Cloudflare would refuse every request. After the health check the deploy asks
    through the edge. Only Caddy's own refusal disarms the check; a 403 Cloudflare
    produced itself says nothing about the Transform Rule."""

    @pytest.fixture
    def run_guard(self, tmp_path):
        bash = shutil.which("bash")
        if not bash:
            pytest.skip("needs bash")
        script = _deploy_script()
        guard = script[script.index("if [ -s caddy.env ]") : script.index("sudo docker image prune")]
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("curl", _STUB_CURL), ("sudo", _STUB_SUDO)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)

        def run(code: str, headers: str):
            (tmp_path / "caddy.env").write_text("ORIGIN_AUTH_SECRET=s3cret\n")
            (tmp_path / "sudo.log").unlink(missing_ok=True)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_CODE": code,
                "STUB_HEADERS": headers,
            }
            proc = subprocess.run(  # noqa: S603 - our own workflow script, stubbed curl/sudo
                [bash, "-c", "set -eu\nIMAGE_TAG=abc123\n" + guard],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            sudo_log = tmp_path / "sudo.log"
            return SimpleNamespace(
                code=proc.returncode,
                out=proc.stdout,
                caddy_env=(tmp_path / "caddy.env").read_text(),
                sudo=sudo_log.read_text() if sudo_log.exists() else "",
            )

        return run

    def test_caddys_refusal_disarms_the_check_and_fails_red(self, run_guard):
        r = run_guard("403", _REFUSED_VIA_CLOUDFLARE)
        assert r.code == 1
        assert r.caddy_env == ""
        assert "::error::" in r.out

    def test_a_refusal_through_cloudflare_names_the_ray_the_reason_and_the_fix(self, run_guard):
        r = run_guard("403", _REFUSED_VIA_CLOUDFLARE)
        assert "8c9d0e1f2a3b4c5d-SIN" in r.out
        assert "X-Origin-Auth absent" in r.out
        assert "scripts/enable_origin_auth.sh" in r.out

    def test_a_refusal_that_skipped_cloudflare_says_so(self, run_guard):
        # No cf-ray: the probe reached Caddy without passing the zone (DNS, /etc/hosts).
        # Still disarmed (availability first), but the fix is not the Transform Rule.
        r = run_guard(
            "403", "HTTP/1.1 403 Forbidden\r\nServer: Caddy\r\nX-Origin-Check: refused; X-Origin-Auth absent\r\n\r\n"
        )
        assert r.code == 1
        assert r.caddy_env == ""
        assert "did not pass through Cloudflare" in r.out
        assert "scripts/enable_origin_auth.sh" not in r.out

    def test_disarming_recreates_only_caddy_on_the_deployed_tag(self, run_guard):
        r = run_guard("403", _REFUSED_VIA_CLOUDFLARE)
        assert "--force-recreate caddy" in r.sudo
        assert "--no-deps" in r.sudo
        assert "BACKEND_IMAGE_TAG=abc123" in r.sudo

    def test_cloudflares_own_403_leaves_the_check_on(self, run_guard):
        # Bot Fight Mode challenging a datacenter IP: answered at the edge, never reached Caddy.
        r = run_guard("403", "HTTP/2 403\r\nserver: cloudflare\r\ncf-mitigated: challenge\r\n\r\n")
        assert r.code == 0
        assert r.caddy_env == "ORIGIN_AUTH_SECRET=s3cret\n"
        assert r.sudo == ""
        assert "::warning::" in r.out
        assert "challenge" in r.out

    def test_an_unreachable_edge_warns_and_leaves_the_check_on(self, run_guard):
        r = run_guard("000", "")
        assert r.code == 0
        assert r.caddy_env == "ORIGIN_AUTH_SECRET=s3cret\n"
        assert "::warning::" in r.out

    def test_a_healthy_edge_passes_quietly(self, run_guard):
        r = run_guard("200", "HTTP/2 200\r\nserver: cloudflare\r\n\r\n")
        assert r.code == 0
        assert r.caddy_env == "ORIGIN_AUTH_SECRET=s3cret\n"
        assert r.sudo == ""
        assert "::" not in r.out


_STUB_CF_CURL = """#!/usr/bin/env bash
# Answers the Cloudflare API by URL; logs writes; the /health probe writes
# $STUB_HEALTH_HEADERS to the -D file and prints $STUB_HEALTH_CODE.
url="" hdrs="" method=GET
while [ $# -gt 0 ]; do
  case "$1" in
    -D) hdrs="$2"; shift ;;
    -X) method="$2"; shift ;;
    https://*) url="$1" ;;
  esac
  shift
done
case "$url" in
  *"/zones?name="*) echo '{"success":true,"result":[{"id":"z1"}]}' ;;
  *"/dns_records"*) printf '%s' "$STUB_DNS" ;;
  *"/entrypoint")
    if [ "$method" = PUT ]; then echo "PUT $url" >> calls.log; echo '{"success":true,"result":{"rules":[{}]}}'
    else echo '{"success":false}'; fi ;;
  *"/health") [ -n "$hdrs" ] && printf '%b' "$STUB_HEALTH_HEADERS" > "$hdrs"; printf '%s' "$STUB_HEALTH_CODE" ;;
  *) echo "unexpected curl $url" >&2; exit 2 ;;
esac
"""

_STUB_INFISICAL = """#!/usr/bin/env bash
case "$1 $2" in
  "secrets get") echo s3cret ;;
  "secrets set") echo "infisical set" >> calls.log ;;
esac
"""

_PROXIED = '{"success":true,"result":[{"type":"A","proxied":true}]}'
_DNS_ONLY = '{"success":true,"result":[{"type":"A","proxied":false}]}'
_VIA_CLOUDFLARE = "HTTP/2 200\r\nserver: cloudflare\r\ncf-ray: 8c9d0e1f2a3b4c5d-SIN\r\n\r\n"


class TestEnableOriginAuthScript:
    """The secret header only arrives on requests that cross the zone. On 2026-10-07
    `api.negolah.my` was DNS-only: the script wrote the rule and stored the secret, its
    probe went straight to Caddy and got 200, and the next deploy's guard had to disarm
    the check. The script now refuses before writing anything unless the record is proxied,
    and its probe must carry `cf-ray`."""

    @pytest.fixture
    def run_script(self, tmp_path):
        bash, jq = shutil.which("bash"), shutil.which("jq")
        if not (bash and jq):
            pytest.skip("needs bash and jq")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("curl", _STUB_CF_CURL), ("infisical", _STUB_INFISICAL)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)

        def run(dns: str, health_code: str = "200", health_headers: str = _VIA_CLOUDFLARE):
            (tmp_path / "calls.log").unlink(missing_ok=True)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "CLOUDFLARE_API_TOKEN": "t",
                "STUB_DNS": dns,
                "STUB_HEALTH_CODE": health_code,
                "STUB_HEALTH_HEADERS": health_headers,
            }
            proc = subprocess.run(  # noqa: S603 - our own script, stubbed curl/infisical
                [bash, str(REPO_ROOT / "scripts" / "enable_origin_auth.sh")],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            calls = tmp_path / "calls.log"
            return SimpleNamespace(
                code=proc.returncode,
                out=proc.stdout + proc.stderr,
                calls=calls.read_text() if calls.exists() else "",
            )

        return run

    def test_a_proxied_record_writes_the_rule_and_stores_the_secret(self, run_script):
        r = run_script(_PROXIED)
        assert r.code == 0, r.out
        assert "PUT " in r.calls
        assert "infisical set" in r.calls
        assert "s3cret" not in r.out

    def test_a_dns_only_record_is_refused_before_anything_is_written(self, run_script):
        r = run_script(_DNS_ONLY)
        assert r.code == 1
        assert r.calls == ""
        assert "Proxied" in r.out

    def test_a_missing_record_is_refused(self, run_script):
        r = run_script('{"success":true,"result":[]}')
        assert r.code == 1
        assert r.calls == ""

    def test_a_token_that_cannot_read_dns_names_the_permission(self, run_script):
        r = run_script('{"success":false,"errors":[{"code":10000,"message":"Authentication error"}]}')
        assert r.code == 1
        assert r.calls == ""
        assert "DNS → Read" in r.out

    def test_a_probe_that_skipped_cloudflare_fails(self, run_script):
        # Proxied at the zone, but this machine resolves the host to the origin (/etc/hosts).
        r = run_script(_PROXIED, health_headers="HTTP/1.1 200 OK\r\nServer: Caddy\r\n\r\n")
        assert r.code == 1
        assert "did not pass through Cloudflare" in r.out
