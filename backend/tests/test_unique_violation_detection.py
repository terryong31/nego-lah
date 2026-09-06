"""
SPEC-037 — a unique-constraint violation is identified by its SQLSTATE.

`_is_unique_violation` decides whether a failed INSERT means "this webhook was
already processed" (benign — go read the existing order) or "something is
actually broken" (log it, bail out). It used to make that call by looking for
"duplicate key" / "already exists" in `str(err)`, which is guesswork on a
string the database formats for humans. A row whose own DATA contains "already
exists" — an item named `"Bundle (already exists)"`, a description quoted back
in an error — reads as a duplicate and the webhook silently swallows a real
failure.

PostgREST's APIError carries the SQLSTATE in `.code`. 23505 IS unique_violation;
any other code is positive evidence it is NOT one. Text matching survives only
for exceptions that carry no code at all.
"""

import pytest
from postgrest.exceptions import APIError

import payment.fulfillment as fulfillment


def _api_error(code, message="insert failed"):
    return APIError({"code": code, "message": message, "hint": None, "details": None})


# ---------------------------------------------------------------------------
# Structured SQLSTATE wins over the message text
# ---------------------------------------------------------------------------

def test_sqlstate_23505_is_a_unique_violation():
    assert fulfillment._is_unique_violation(_api_error("23505")) is True


def test_sqlstate_23505_recognised_regardless_of_message():
    assert fulfillment._is_unique_violation(
        _api_error("23505", "connection refused")
    ) is True


@pytest.mark.parametrize("code", ["23503", "23502", "42501", "40001", "PGRST301"])
def test_other_sqlstates_are_not_unique_violations(code):
    """A foreign-key violation whose message happens to say "duplicate key" is
    still a foreign-key violation. The code is the answer, not the prose."""
    assert fulfillment._is_unique_violation(
        _api_error(code, "duplicate key value violates unique constraint")
    ) is False


def test_foreign_key_violation_is_not_swallowed_as_idempotency():
    err = _api_error("23503", 'Key (item_id)=(x) already exists in some other table')
    assert fulfillment._is_unique_violation(err) is False


# ---------------------------------------------------------------------------
# Fallback: exceptions with no SQLSTATE at all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "duplicate key value violates unique constraint",
    "ERROR: 23505: duplicate key",
    "Key (stripe_payment_id)=(pi_123) already exists.",
    'violates unique constraint "orders_stripe_payment_id_key"',
    "DUPLICATE KEY VALUE",
])
def test_plain_exception_falls_back_to_text_matching(message):
    assert fulfillment._is_unique_violation(Exception(message)) is True


@pytest.mark.parametrize("message", [
    "connection refused",
    "permission denied for table orders",
    "timeout",
    "",
])
def test_plain_exception_without_duplicate_wording_is_false(message):
    assert fulfillment._is_unique_violation(Exception(message)) is False


def test_empty_code_falls_back_to_text():
    """PostgREST fills `code` with None for some transport-level failures."""
    assert fulfillment._is_unique_violation(
        _api_error(None, "duplicate key value violates unique constraint")
    ) is True
