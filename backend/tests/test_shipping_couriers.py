"""The courier registry (SPEC-057).

A tracking number the buyer has to copy into a search engine is a worse version
of a link. The registry exists to turn "J&T, 630123456789" into something
clickable — and, just as importantly, to shrug when it cannot: an unknown
carrier is still worth recording, so a miss returns None rather than raising.
"""

import pytest

from domains.catalog.shipping import (
    COURIER_CHOICES,
    normalise_courier,
    resolve_tracking_url,
)


@pytest.mark.parametrize("typed", ["J&T Express", "j&t express", "  J&T  ", "jt", "JT Express"])
def test_a_courier_is_recognised_however_the_seller_typed_it(typed):
    """The seller is typing into a form at speed, not filling in a key."""
    assert normalise_courier(typed) == "J&T Express"


def test_an_unknown_courier_is_kept_as_typed():
    assert normalise_courier("Some Local Bike Guy") == "Some Local Bike Guy"
    assert normalise_courier("  spaced  out  ") == "spaced out"


def test_a_blank_courier_normalises_to_nothing():
    assert normalise_courier("") is None
    assert normalise_courier("   ") is None
    assert normalise_courier(None) is None


def test_a_known_courier_yields_a_tracking_url_with_the_number_in_it():
    url = resolve_tracking_url("J&T Express", "630123456789")
    assert url and url.startswith("https://")
    assert "630123456789" in url


def test_tracking_numbers_are_url_encoded():
    url = resolve_tracking_url("Pos Laju", "ABC 123/45")
    assert " " not in url
    assert "/45" not in url.split("?")[-1].replace("%2F", "")


def test_an_unknown_courier_yields_no_url_rather_than_a_broken_one():
    assert resolve_tracking_url("Some Local Bike Guy", "12345") is None


def test_no_url_without_a_tracking_number():
    assert resolve_tracking_url("J&T Express", "") is None
    assert resolve_tracking_url("J&T Express", None) is None


def test_every_registered_courier_has_a_working_https_template():
    for value in COURIER_CHOICES:
        url = resolve_tracking_url(value, "TESTCODE1")
        assert url is not None, f"{value} is offered as a choice but resolves no URL"
        assert url.startswith("https://"), f"{value} must track over https"
        assert "TESTCODE1" in url, f"{value}'s template drops the tracking number"


def test_the_choices_are_the_canonical_names():
    """The console renders COURIER_CHOICES directly, so each has to round-trip."""
    for value in COURIER_CHOICES:
        assert normalise_courier(value) == value
