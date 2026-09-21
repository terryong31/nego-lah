"""
Every admin route is gated (SPEC-095).

`admin_api.py` has always claimed this file exists. It did not. The claim was
load-bearing — the module's whole design is "a domain declares a plain
`APIRouter()` and never has to remember to gate itself, because `admin_api.py`
mounts it under `protected`" — and the failure mode it guards against is a
router quietly mounted on the public `router` instead, which looks like a
working endpoint in every other test.

Asserted by driving unauthenticated requests rather than by reading the
dependency list, because this FastAPI version composes router-level
dependencies at request time: a route's `dependant` does not carry what it
inherited from `protected`, so introspection would report every route as
ungated and prove nothing.
"""

import re

import pytest

from core.env import ADMIN_PREFIX

# The two routes that establish a session. They cannot require one, so they are
# the only admin routes allowed past `verify_admin` — and naming them here means
# a third one cannot be added without this list changing.
SESSION_ESTABLISHING = {
    ("POST", f"{ADMIN_PREFIX}/auth/login"),
    ("POST", f"{ADMIN_PREFIX}/auth/verify-2fa"),
}


def _walk(routes, prefix=""):
    """Flatten the app's route tree into (full path, route) pairs.

    `include_router` keeps each router as an `_IncludedRouter` node holding the
    real one under `original_router`, and each route stores its path without the
    prefix it was mounted under — so the prefix has to be carried down.
    """
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _walk(nested.routes, prefix + getattr(nested, "prefix", ""))
        elif hasattr(route, "dependant"):
            yield prefix + route.path, route


def _admin_operations(app):
    operations = []
    for path, route in _walk(app.routes):
        if not path.startswith(ADMIN_PREFIX):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operations.append((method, path))
    return sorted(operations)


@pytest.fixture
def admin_operations(app):
    return _admin_operations(app)


def test_the_admin_surface_is_not_empty(admin_operations):
    """Guard the guard: an empty list would make every assertion below vacuous."""
    assert len(admin_operations) > 20, f"only found {len(admin_operations)} admin operations — the walk is broken"


def test_every_session_establishing_route_still_exists(admin_operations):
    """If one is renamed, the exemption below must be revisited, not silently widened."""
    missing = SESSION_ESTABLISHING - set(admin_operations)
    assert not missing, f"exempted routes that no longer exist: {sorted(missing)}"


async def test_no_admin_route_answers_without_a_session(client, admin_operations):
    """
    The one that matters. An ungated admin route returns anything but 401/403
    here — 200 if it just works, 422 if it validates a body first, 500 if it
    reaches a database it should never have reached.
    """
    ungated = []
    for method, path in admin_operations:
        if (method, path) in SESSION_ESTABLISHING:
            continue
        url = re.sub(r"\{[^}]+\}", "placeholder", path)
        response = await client.request(method, url, json={})
        if response.status_code not in (401, 403):
            ungated.append(f"  {method} {path} -> {response.status_code}")

    assert not ungated, (
        "Admin routes reachable without a session — check they are mounted on "
        "`protected` in admin_api.py, not on the public router:\n" + "\n".join(ungated)
    )


async def test_the_login_route_is_reachable_without_a_session(client):
    """The exemption is real, not an accident of the test: login must answer."""
    response = await client.post(f"{ADMIN_PREFIX}/auth/login", json={})
    assert response.status_code not in (401, 403)
