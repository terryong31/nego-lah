"""
Tests for agent/context.py — request-scoped ContextVar-based user/item context.

These are pure unit tests with no FastAPI app, Supabase, or Stripe involved,
since agent/context.py has zero external dependencies (just `contextvars`).
"""

import asyncio

import pytest

from agent.context import current_item_id, current_user_id, get_item_id, get_user_id, set_context


@pytest.fixture(autouse=True)
def _reset_context_vars():
    """agent/context.py's ContextVars live on the *ambient* thread context.

    A plain (sync) test function runs directly in that ambient context (it is
    not wrapped in its own asyncio Task the way async tests are), so a
    `set_context(...)` call in one sync test would otherwise permanently
    mutate the context and leak into every test that runs afterwards. Save a
    reset Token before each test and restore it afterwards so tests are
    order-independent.
    """
    user_token = current_user_id.set(None)
    item_token = current_item_id.set(None)
    try:
        yield
    finally:
        current_user_id.reset(user_token)
        current_item_id.reset(item_token)


def test_defaults_are_none_when_unset():
    """Before any set_context() call in this task's context, both getters return None."""
    assert get_user_id() is None
    assert get_item_id() is None


def test_set_context_roundtrip():
    """set_context() populates both values, retrievable via the getters."""
    set_context(user_id="user-123", item_id="item-456")

    assert get_user_id() == "user-123"
    assert get_item_id() == "item-456"


def test_set_context_no_args_resets_to_none():
    """Calling set_context() with no arguments always (re)sets both vars to their
    default of None — it does not leave previously-set values untouched."""
    set_context(user_id="user-123", item_id="item-456")
    assert get_user_id() == "user-123"
    assert get_item_id() == "item-456"

    set_context()

    assert get_user_id() is None
    assert get_item_id() is None


def test_set_context_partial_user_id_only():
    """Passing only user_id still overwrites item_id back to its default (None) —
    set_context() is not a merge/patch, it always sets both vars each call."""
    set_context(user_id="user-1", item_id="item-1")

    set_context(user_id="user-2")

    assert get_user_id() == "user-2"
    assert get_item_id() is None


def test_set_context_partial_item_id_only():
    """Symmetric case: passing only item_id resets user_id back to None."""
    set_context(user_id="user-1", item_id="item-1")

    set_context(item_id="item-2")

    assert get_user_id() is None
    assert get_item_id() == "item-2"


def test_context_vars_are_contextvar_instances():
    """Sanity-check the module exposes real contextvars.ContextVar objects with
    the documented default of None."""
    import contextvars

    assert isinstance(current_user_id, contextvars.ContextVar)
    assert isinstance(current_item_id, contextvars.ContextVar)
    assert current_user_id.name == "current_user_id"
    assert current_item_id.name == "current_item_id"


async def test_per_task_isolation_no_cross_contamination():
    """Two concurrently-running asyncio tasks each set_context() to different
    values; because ContextVars are per-Task, neither should observe the
    other's values at any point during execution."""

    async def worker(user_id, item_id, delay_before, delay_after):
        # Stagger start slightly so the two tasks' set/get calls interleave
        # rather than running back-to-back.
        await asyncio.sleep(delay_before)
        set_context(user_id=user_id, item_id=item_id)
        # Yield control back to the event loop so the other task can run
        # in between this task's set_context() and its read-back below.
        await asyncio.sleep(delay_after)
        return get_user_id(), get_item_id()

    result_a, result_b = await asyncio.gather(
        worker("user-A", "item-A", delay_before=0.0, delay_after=0.02),
        worker("user-B", "item-B", delay_before=0.01, delay_after=0.0),
    )

    assert result_a == ("user-A", "item-A")
    assert result_b == ("user-B", "item-B")

    # The gather() call itself runs inside the current test's own task context,
    # so this test's top-level context should be untouched by either worker.
    assert get_user_id() is None
    assert get_item_id() is None


async def test_context_set_inside_task_does_not_leak_to_caller():
    """A context set inside a spawned child task must not leak back out to the
    task that created it (asyncio.Task copies the context at creation time)."""

    async def child():
        set_context(user_id="child-user", item_id="child-item")
        assert get_user_id() == "child-user"

    assert get_user_id() is None

    task = asyncio.create_task(child())
    await task

    # The parent task's context is unaffected by what the child set.
    assert get_user_id() is None
    assert get_item_id() is None
