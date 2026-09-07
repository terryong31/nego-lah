"""SPEC-043 Workstream C — the host is divided, not shared first-come.

Caddy, the API and Redis all run on one 2 GB / 1–2 vCPU Lightsail box. With no
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


@pytest.mark.parametrize("service", ["caddy", "backend", "redis"])
def test_every_service_declares_a_memory_limit(services, service):
    """One unbounded container can OOM the box and take the other two down."""
    assert "mem_limit" in services[service], (
        f"{service} has no mem_limit — it can consume the whole host"
    )
    assert _mem_bytes(services[service]["mem_limit"]) > 0


def test_memory_limits_leave_headroom_for_the_host(services):
    """The three containers must not be allowed to claim the entire 2 GB;
    the kernel, sshd and the Docker daemon still need somewhere to live."""
    total = sum(_mem_bytes(services[s]["mem_limit"]) for s in ("caddy", "backend", "redis"))
    box = 2 * 1024**3
    assert total < box * 0.85, (
        f"limits total {total / 1024**3:.2f} GB of a 2 GB box — too little headroom"
    )


@pytest.mark.parametrize("service", ["caddy", "redis"])
def test_supporting_services_cannot_monopolise_the_cpu(services, service):
    """Caddy and Redis are cheap and must stay cheap. A hard ceiling on the two
    of them is what guarantees the API can't be starved by its own sidecars."""
    assert "cpus" in services[service], f"{service} has no cpus ceiling"
    assert float(services[service]["cpus"]) <= 0.5


def test_redis_is_memory_capped_and_evicts_rather_than_dying(services):
    """`mem_limit` alone just moves the failure: Redis grows into its cap and
    gets OOM-killed. `maxmemory` plus a policy makes it evict instead — and
    `volatile-ttl` is the right policy here because nearly every key this app
    writes already carries one."""
    command = " ".join(services["redis"].get("command", []) or [])
    assert "--maxmemory" in command, "redis has no maxmemory — it can grow until killed"
    assert "--maxmemory-policy" in command

    # The eviction ceiling must sit below the container's own hard limit, or
    # the kernel kills the process before Redis ever starts evicting.
    maxmemory = command.split("--maxmemory ")[1].split()[0]
    assert _mem_bytes(maxmemory) < _mem_bytes(services["redis"]["mem_limit"])


def test_worker_count_is_pinned_explicitly(services):
    """The Dockerfile's `${WEB_CONCURRENCY:-4}` put 4 workers on a 1–2 vCPU box
    by default. Whatever the number ends up being, it should be a stated
    decision in the deployment manifest rather than an inherited fallback."""
    env = services["backend"].get("environment", [])
    entries = env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()]
    concurrency = [e for e in entries if str(e).startswith("WEB_CONCURRENCY")]

    assert concurrency, "WEB_CONCURRENCY is not set explicitly for the backend"
    workers = int(str(concurrency[0]).split("=", 1)[1])
    assert 1 <= workers <= 2, (
        f"{workers} workers on a documented 1–2 vCPU host is oversubscribed"
    )
