"""SPEC-043 Workstream C — the host is divided, not shared first-come.

Caddy and the API run on one 2 GB / 1–2 vCPU Lightsail box. (Redis did too
until production moved to managed Upstash; the sidecar was retired on
2026-10-07 once the live backend was confirmed writing there.) With no
limits declared, Docker lets them compete for the whole host: a CPU spike in
the API slows the Redis it depends on for auth, rate limiting and leases —
which slows every request, including the ones that weren't busy. Redis with no
`maxmemory` is the sharper edge: unbounded growth ends in the OOM killer,
which takes neighbours with it.

These assertions are about the deployment manifest, so they're config tests,
not behaviour tests — the same shape as `test_spec_registry.py`.
"""

import pathlib

import pytest
import yaml

COMPOSE_PATH = pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.fixture(scope="module")
def services(compose):
    return compose["services"]


def _mem_bytes(value: str) -> int:
    """Parse a memory size into bytes.

    Handles both spellings in play here: Compose's `mem_limit` ('256m', '1g')
    and Redis's `--maxmemory` ('192mb'), which appends an explicit 'b'.
    """
    text = str(value).strip().lower().removesuffix("b")
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(text)


@pytest.mark.parametrize("service", ["caddy", "backend"])
def test_every_service_declares_a_memory_limit(services, service):
    """One unbounded container can OOM the box and take the other two down."""
    assert "mem_limit" in services[service], f"{service} has no mem_limit — it can consume the whole host"
    assert _mem_bytes(services[service]["mem_limit"]) > 0


def test_memory_limits_leave_headroom_for_the_host(services):
    """The containers must not be allowed to claim the entire 2 GB; the
    kernel, sshd and the Docker daemon still need somewhere to live."""
    total = sum(_mem_bytes(services[s]["mem_limit"]) for s in services)
    box = 2 * 1024**3
    assert total < box * 0.85, f"limits total {total / 1024**3:.2f} GB of a 2 GB box — too little headroom"


@pytest.mark.parametrize("service", ["caddy"])
def test_supporting_services_cannot_monopolise_the_cpu(services, service):
    """Caddy is cheap and must stay cheap. A hard ceiling on it is what
    guarantees the API can't be starved by its own proxy."""
    assert "cpus" in services[service], f"{service} has no cpus ceiling"
    assert float(services[service]["cpus"]) <= 0.5


def test_production_redis_is_managed_not_a_sidecar(compose, services):
    """Production talks to Upstash through the `REDIS_URL` secret. A local
    `redis` service would only be a second, silently divergent Redis — and
    `depends_on` it gated backend startup on a container nothing used."""
    assert "redis" not in services
    assert "redis" not in (services["backend"].get("depends_on") or {})
    assert "redis_data" not in (compose.get("volumes") or {})


def test_redis_url_is_not_pinned_in_the_manifest(services):
    """Compose `environment:` outranks `env_file:`; pinning REDIS_URL here is
    exactly how prod once kept talking to the sidecar whatever the secret said."""
    env = services["backend"].get("environment", [])
    entries = env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()]
    assert not [e for e in entries if str(e).startswith("REDIS_URL")]


def test_worker_count_is_pinned_explicitly(services):
    """The Dockerfile's `${WEB_CONCURRENCY:-4}` put 4 workers on a 1–2 vCPU box
    by default. Whatever the number ends up being, it should be a stated
    decision in the deployment manifest rather than an inherited fallback."""
    env = services["backend"].get("environment", [])
    entries = env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()]
    concurrency = [e for e in entries if str(e).startswith("WEB_CONCURRENCY")]

    assert concurrency, "WEB_CONCURRENCY is not set explicitly for the backend"
    workers = int(str(concurrency[0]).split("=", 1)[1])
    assert 1 <= workers <= 2, f"{workers} workers on a documented 1–2 vCPU host is oversubscribed"
