"""Per-IP ceilings have to survive a roomful of people sharing one IP.

Found while load testing SPEC-043 before a 1000-person conference. The per-IP
limits added in workstream D were sized as though one IP meant one person.
Behind NAT — conference wifi, an office, a university, mobile carriers — one
IP means *everyone*, so `NOTIFICATION_STREAM_LIMIT = 30/minute` meant the 31st
attendee to open the app got a 429, and `CATALOG_LIMIT = 120/minute` meant the
storefront stopped loading for the whole room seconds into a demo.

Measured against the rig: 40 notification-stream opens from a single simulated
NAT address produced 10 × 429.

So these ceilings are deliberately coarse. They exist to stop one scripted
laptop saturating the box, and nothing else — per-person fairness is the job of
the per-user limiter in `cache.check_rate_limit`, which keys on the
authenticated user and is unaffected by how many people share an address.

The env overrides matter for the same reason: a venue that turns out to be
busier than expected can be dialled without a rebuild.
"""

import os
import pathlib
import subprocess
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import limiter as limiter_module  # noqa: E402


def _per_minute(value: str) -> int:
    amount, _, window = value.partition("/")
    assert window.strip() in ("minute", "min"), f"unexpected window in {value!r}"
    return int(amount.strip())


# A conservative floor: 250 concurrent users was the point where the box
# started to slow under load testing, and a browsing session is a handful of
# requests. Anything below this and normal use trips the limit.
ROOM_SIZE = 250


def test_catalog_ceiling_survives_a_room_on_one_ip():
    """Every attendee opening the storefront a few times must not exhaust it."""
    assert _per_minute(limiter_module.CATALOG_LIMIT) >= ROOM_SIZE * 4


def test_notification_stream_ceiling_survives_a_room_on_one_ip():
    """One connection per tab, plus a reconnect whenever wifi hiccups — which
    at a conference is constantly."""
    assert _per_minute(limiter_module.NOTIFICATION_STREAM_LIMIT) >= ROOM_SIZE * 4


def test_checkout_ceiling_survives_a_room_on_one_ip():
    assert _per_minute(limiter_module.CHECKOUT_LIMIT) >= ROOM_SIZE


@pytest.mark.parametrize(
    "env_var,attr",
    [
        ("CATALOG_RATE_LIMIT", "CATALOG_LIMIT"),
        ("NOTIFICATION_STREAM_RATE_LIMIT", "NOTIFICATION_STREAM_LIMIT"),
        ("CHECKOUT_RATE_LIMIT", "CHECKOUT_LIMIT"),
    ],
)
def test_each_ceiling_can_be_retuned_without_a_rebuild(env_var, attr):
    """Imported in a subprocess deliberately.

    Reloading `limiter` in-process rebinds the module's `limiter` object, but
    every `@limiter.limit(...)` already applied to a route still refers to the
    old instance — so the reloaded one has no registered limits and
    `app.state.limiter` no longer matches the decorators. That silently breaks
    unrelated tests; a subprocess can't reach back into this one.
    """
    env = {**os.environ, env_var: "4321/minute"}
    # S603: the argv is this test's own literals, not user input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", f"import limiter; print(limiter.{attr})"],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "4321/minute"


def test_defaults_are_still_a_real_ceiling():
    """Coarse is the point; absent is not. A limit high enough to be useless
    would leave the box with no flood protection at all."""
    for value in (
        limiter_module.CATALOG_LIMIT,
        limiter_module.NOTIFICATION_STREAM_LIMIT,
        limiter_module.CHECKOUT_LIMIT,
    ):
        assert _per_minute(value) <= 20_000
