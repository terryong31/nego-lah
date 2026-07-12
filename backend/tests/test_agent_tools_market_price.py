"""Tests for agent/tools/market_price.py (MarketPriceService).

`_estimate_price` imports `ChatGoogleGenerativeAI` LAZILY inside the method
body (`from langchain_google_genai import ChatGoogleGenerativeAI`), so
patching `agent.tools.market_price.ChatGoogleGenerativeAI` would have no
effect (that name doesn't exist in this module's namespace at all -- it's
never imported at module scope). Instead we monkeypatch
`langchain_google_genai.ChatGoogleGenerativeAI` (the class, in its origin
module) so the lazy `from ... import ...` resolves to our fake at call time.

The method also does `from env import GEMINI_API_KEY` lazily on every call,
so monkeypatching `env.GEMINI_API_KEY` (rather than
`agent.tools.market_price.GEMINI_API_KEY`, which also doesn't exist as a
module-level name here) takes effect immediately for the next call.

The whole `_estimate_price` Gemini-grounding path is wrapped in a broad
`try/except Exception` that falls back to `_fallback_estimate_price` on
*any* failure (missing API key, bad JSON, network/SDK errors, ...) -- we
exercise both branches.

`market_service` (the module-level singleton) is used for a couple of tests
solely to confirm it's constructed correctly; all other tests instantiate a
fresh `MarketPriceService()` to avoid any possibility of cross-test state
bleed (there isn't any instance state today, but the singleton is a shared
mutable object across the whole test session).
"""

import json

from agent.tools.market_price import (
    CATEGORY_BASE_PRICES,
    CONDITION_MULTIPLIERS,
    MarketPriceService,
    market_service,
)


# ---------------------------------------------------------------------------
# Module-level singleton sanity check
# ---------------------------------------------------------------------------
def test_market_service_singleton_is_market_price_service_instance():
    assert isinstance(market_service, MarketPriceService)


# ---------------------------------------------------------------------------
# _round_price -- Malaysian psychological pricing
# ---------------------------------------------------------------------------
def test_round_price_below_10_rounds_to_2_decimals():
    svc = MarketPriceService()
    assert svc._round_price(5.6789) == 5.68
    assert svc._round_price(0.0) == 0.0


def test_round_price_below_10_boundary_rounds_up_across_threshold():
    # 9.999 rounds (to 2dp) to 10.0, but note this still uses the <10
    # "round to 2dp" branch (the branch check happens on the *raw* price,
    # before rounding), not the 10-99 psychological-pricing branch.
    svc = MarketPriceService()
    assert svc._round_price(9.999) == 10.0


def test_round_price_10_to_99_small_decimal_rounds_down_to_whole():
    svc = MarketPriceService()
    # decimal (0.2) < 0.3 -> plain whole number
    assert svc._round_price(45.2) == 45.0


def test_round_price_10_to_99_mid_decimal_uses_dot_88():
    svc = MarketPriceService()
    # 0.3 <= decimal (0.5) < 0.7 -> base + 0.88
    assert svc._round_price(45.5) == 45.88


def test_round_price_10_to_99_high_decimal_uses_dot_90():
    svc = MarketPriceService()
    # decimal (0.8) >= 0.7 -> base + 0.90
    assert svc._round_price(45.8) == 45.9


def test_round_price_exactly_10_uses_10_to_99_branch():
    svc = MarketPriceService()
    # 10 is NOT < 10, so it falls into the 10-99 branch: base=10, decimal=0.
    assert svc._round_price(10) == 10.0


def test_round_price_exactly_100_uses_100_plus_branch():
    svc = MarketPriceService()
    # 100 is NOT < 100, so it falls into the >=100 branch:
    # round(100/5)*5 = 100, which is < 500 -> 100 - 0.10.
    assert svc._round_price(100) == 99.9


def test_round_price_100_plus_below_500_subtracts_10_cents():
    svc = MarketPriceService()
    # round(102/5)*5 = round(20.4)*5 = 20*5 = 100 -> 100 - 0.10
    assert svc._round_price(102) == 99.9
    # round(497/5)*5 = round(99.4)*5 = 99*5 = 495 -> 495 - 0.10
    assert svc._round_price(497) == 494.9


def test_round_price_100_plus_at_or_above_500_no_subtraction():
    svc = MarketPriceService()
    # round(498/5)*5 = round(99.6)*5 = 100*5 = 500 -> NOT < 500 -> plain 500.0
    assert svc._round_price(498) == 500.0
    # round(600/5)*5 = 600 -> plain 600.0
    assert svc._round_price(600) == 600.0


# ---------------------------------------------------------------------------
# _infer_category
# ---------------------------------------------------------------------------
def test_infer_category_electronics_keyword():
    svc = MarketPriceService()
    assert svc._infer_category("iPhone 13") == "electronics"


def test_infer_category_electronics_watch_keyword_wins_over_no_fashion_match():
    svc = MarketPriceService()
    assert svc._infer_category("Rolex watch") == "electronics"


def test_infer_category_fashion_keyword():
    svc = MarketPriceService()
    assert svc._infer_category("Nike shoes") == "fashion"
    assert svc._infer_category("Gucci bag") == "fashion"


def test_infer_category_sports_keyword():
    svc = MarketPriceService()
    assert svc._infer_category("badminton racket") == "sports"


def test_infer_category_sports_checked_before_vehicles_for_overlapping_bike_keyword():
    """`"bike"` appears in BOTH sports_keywords and vehicles_keywords, but
    sports_keywords is checked first in the loop order, so any query
    matching only on "bike" resolves to "sports", never "vehicles"."""
    svc = MarketPriceService()
    assert svc._infer_category("mountain bike") == "sports"


def test_infer_category_home_keyword():
    svc = MarketPriceService()
    assert svc._infer_category("wooden dining table") == "home"
    assert svc._infer_category("sofa set") == "home"


def test_infer_category_vehicles_keyword():
    svc = MarketPriceService()
    assert svc._infer_category("Toyota Vios") == "vehicles"
    assert svc._infer_category("Honda motorcycle") == "vehicles"


def test_infer_category_no_keyword_match_returns_other():
    svc = MarketPriceService()
    assert svc._infer_category("a mysterious item") == "other"
    assert svc._infer_category("") == "other"


def test_infer_category_is_case_insensitive():
    svc = MarketPriceService()
    assert svc._infer_category("SAMSUNG GALAXY") == "electronics"


# ---------------------------------------------------------------------------
# _fallback_estimate_price
# ---------------------------------------------------------------------------
def test_fallback_estimate_price_explicit_category_and_condition():
    svc = MarketPriceService()
    result = svc._fallback_estimate_price("test", "new", "electronics")

    assert result == {
        "market_average": 494.9,
        "min_price": 99.0,
        "max_price": 1985.0,
        "suggested_listing": 454.9,
        "currency": "MYR",
        "source": "Estimation (Fallback)",
        "category_detected": "electronics",
        "condition_used": "new",
    }


def test_fallback_estimate_price_infers_category_when_none_given():
    svc = MarketPriceService()
    # category=None -> falls back to self._infer_category(query), and
    # condition="" -> falsy -> defaults to "good".
    result = svc._fallback_estimate_price("mysterious gadget", "", None)

    assert result["category_detected"] == "other"
    assert result["condition_used"] == "good"
    assert result == {
        "market_average": 77.0,
        "min_price": 15.88,
        "max_price": 384.9,
        "suggested_listing": 71.0,
        "currency": "MYR",
        "source": "Estimation (Fallback)",
        "category_detected": "other",
        "condition_used": "good",
    }


def test_fallback_estimate_price_unknown_condition_uses_default_multiplier():
    svc = MarketPriceService()
    # "excellent" isn't in CONDITION_MULTIPLIERS -> .get(..., 0.70) default.
    result = svc._fallback_estimate_price("random book", "excellent", "books")

    assert result["condition_used"] == "excellent"
    assert result == {
        "market_average": 14.0,
        "min_price": 2.8,
        "max_price": 56.0,
        "suggested_listing": 12.9,
        "currency": "MYR",
        "source": "Estimation (Fallback)",
        "category_detected": "books",
        "condition_used": "excellent",
    }


def test_fallback_estimate_price_unknown_category_falls_back_to_other_base():
    svc = MarketPriceService()
    # An explicit category that isn't a key in CATEGORY_BASE_PRICES at all
    # (bypassing _infer_category entirely, since it was passed directly)
    # falls back to CATEGORY_BASE_PRICES["other"] for the price base, but
    # category_detected still reports the (lowercased) unknown category.
    result = svc._fallback_estimate_price("something", "good", "spaceship")

    assert result["category_detected"] == "spaceship"
    assert result == {
        "market_average": 76.9,
        "min_price": 15.88,
        "max_price": 384.9,
        "suggested_listing": 70.88,
        "currency": "MYR",
        "source": "Estimation (Fallback)",
        "category_detected": "spaceship",
        "condition_used": "good",
    }


def test_fallback_estimate_price_category_and_condition_are_lowercased():
    svc = MarketPriceService()
    result = svc._fallback_estimate_price("test", "NEW", "ELECTRONICS")
    assert result["category_detected"] == "electronics"
    assert result["condition_used"] == "new"


def test_fallback_estimate_price_uses_every_category_base_price_key():
    """Sanity sweep: every declared category resolves without KeyError and
    produces plausible (positive, ordered) min <= average <= max prices."""
    svc = MarketPriceService()
    for category in CATEGORY_BASE_PRICES:
        result = svc._fallback_estimate_price("widget", "good", category)
        assert result["category_detected"] == category
        assert result["min_price"] <= result["market_average"] <= result["max_price"]


def test_fallback_estimate_price_uses_every_condition_multiplier_key():
    svc = MarketPriceService()
    for condition in CONDITION_MULTIPLIERS:
        result = svc._fallback_estimate_price("widget", condition, "other")
        assert result["condition_used"] == condition


# ---------------------------------------------------------------------------
# _analyze_scraped_prices
# ---------------------------------------------------------------------------
def test_analyze_scraped_prices_with_items_computes_stats():
    svc = MarketPriceService()
    items = [{"price": 100}, {"price": 200}, {"price": 300}]

    result = svc._analyze_scraped_prices(items, "new")

    # multiplier for "new" == 1.0
    assert result["market_average"] == svc._round_price(200.0)
    assert result["min_price"] == svc._round_price(100.0)
    assert result["max_price"] == svc._round_price(300.0)
    assert result["suggested_listing"] == svc._round_price(200.0 * 0.92)
    assert result["currency"] == "MYR"
    assert result["source"] == "Scraped Data"
    assert result["sample_size"] == 3


def test_analyze_scraped_prices_applies_condition_multiplier():
    svc = MarketPriceService()
    items = [{"price": 100}]

    result = svc._analyze_scraped_prices(items, "fair")

    # multiplier for "fair" == 0.55
    assert result["market_average"] == svc._round_price(55.0)
    assert result["sample_size"] == 1


def test_analyze_scraped_prices_condition_is_case_insensitive():
    svc = MarketPriceService()
    items = [{"price": 100}]

    result = svc._analyze_scraped_prices(items, "FAIR")

    assert result["market_average"] == svc._round_price(55.0)


def test_analyze_scraped_prices_unknown_condition_uses_default_multiplier():
    svc = MarketPriceService()
    items = [{"price": 100}]

    result = svc._analyze_scraped_prices(items, "excellent")

    assert result["market_average"] == svc._round_price(70.0)


def test_analyze_scraped_prices_filters_out_falsy_prices():
    svc = MarketPriceService()
    items = [{"price": 100}, {"price": 0}, {"price": None}, {}]

    result = svc._analyze_scraped_prices(items, "new")

    # Only the {"price": 100} entry survives the `if item.get("price")` filter.
    assert result["sample_size"] == 1
    assert result["market_average"] == svc._round_price(100.0)


def test_analyze_scraped_prices_empty_items_delegates_to_estimate_price(monkeypatch):
    """When every item has no usable price, `_analyze_scraped_prices` falls
    through to `self._estimate_price("", condition)` -- verified here by
    monkeypatching that method so this test never touches the network."""
    svc = MarketPriceService()
    sentinel = {"source": "sentinel"}
    called_with = {}

    def fake_estimate(query, condition, category=None):
        called_with["query"] = query
        called_with["condition"] = condition
        return sentinel

    monkeypatch.setattr(svc, "_estimate_price", fake_estimate)

    result = svc._analyze_scraped_prices([], "good")

    assert result is sentinel
    assert called_with == {"query": "", "condition": "good"}


# ---------------------------------------------------------------------------
# get_market_valuation / _estimate_price -- Gemini Google Search Grounding
# ---------------------------------------------------------------------------
def _make_fake_chat_model(content):
    """Build a fake replacement for `ChatGoogleGenerativeAI` whose
    `.bind(tools=...).invoke([...])` returns an object with `.content`."""
    from unittest.mock import MagicMock

    fake_response = MagicMock()
    fake_response.content = content

    fake_grounded_model = MagicMock()
    fake_grounded_model.invoke.return_value = fake_response

    fake_model_instance = MagicMock()
    fake_model_instance.bind.return_value = fake_grounded_model

    fake_class = MagicMock(return_value=fake_model_instance)
    return fake_class, fake_model_instance, fake_grounded_model


def test_get_market_valuation_success_parses_plain_json(monkeypatch):
    content = json.dumps({
        "market_average": 500.0,
        "min_price": 100.0,
        "max_price": 900.0,
        "suggested_listing": 460.0,
    })
    fake_class, fake_instance, fake_grounded = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc.get_market_valuation("iPhone 13", condition="good", category="electronics")

    assert result == {
        "market_average": 500.0,
        "min_price": 100.0,
        "max_price": 900.0,
        "suggested_listing": 460.0,
        "currency": "MYR",
        "source": "Google Search (AI)",
        "category_detected": "electronics",
        "condition_used": "good",
    }
    # Confirms grounding tool was wired up correctly.
    fake_instance.bind.assert_called_once_with(tools=[{"google_search": {}}])
    fake_grounded.invoke.assert_called_once()


def test_get_market_valuation_success_category_none_reports_unknown(monkeypatch):
    content = json.dumps({
        "market_average": 10.0, "min_price": 5.0, "max_price": 20.0, "suggested_listing": 9.0,
    })
    fake_class, _, _ = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc.get_market_valuation("some widget", condition="good", category=None)

    assert result["category_detected"] == "unknown"
    assert result["source"] == "Google Search (AI)"


def test_get_market_valuation_success_strips_markdown_code_fences(monkeypatch):
    content = "```json\n" + json.dumps({
        "market_average": 42.0, "min_price": 10.0, "max_price": 80.0, "suggested_listing": 39.0,
    }) + "\n```"
    fake_class, _, _ = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc._estimate_price("widget", "good", "other")

    assert result["market_average"] == 42.0
    assert result["source"] == "Google Search (AI)"


def test_get_market_valuation_success_extracts_json_amid_surrounding_text(monkeypatch):
    payload = json.dumps({
        "market_average": 15.0, "min_price": 5.0, "max_price": 25.0, "suggested_listing": 14.0,
    })
    content = f"Here is my analysis:\n{payload}\nHope that helps!"
    fake_class, _, _ = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc._estimate_price("widget", "good", "other")

    assert result["market_average"] == 15.0
    assert result["source"] == "Google Search (AI)"


def test_get_market_valuation_success_content_as_list_of_dict_parts(monkeypatch):
    """Some Gemini responses return `.content` as a list of parts instead
    of a plain string; the code joins string parts and dict parts' `text`
    key together before parsing."""
    payload = json.dumps({
        "market_average": 77.0, "min_price": 20.0, "max_price": 150.0, "suggested_listing": 70.0,
    })
    # Includes a part that is neither a plain string nor a dict with a
    # 'text' key (e.g. a dict carrying some other metadata field) -- it is
    # silently skipped by the join logic rather than raising.
    content = ["prefix text ", {"other": "ignored"}, {"text": payload}]
    fake_class, _, _ = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc._estimate_price("widget", "good", "other")

    assert result["market_average"] == 77.0
    assert result["source"] == "Google Search (AI)"


def test_get_market_valuation_success_missing_json_fields_default_to_zero(monkeypatch):
    # Only market_average and min_price present; max_price/suggested_listing
    # should default to 0 via `data.get(..., 0)`.
    content = json.dumps({"market_average": 55.0, "min_price": 10.0})
    fake_class, _, _ = _make_fake_chat_model(content)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    result = svc._estimate_price("widget", "good", "other")

    assert result["market_average"] == 55.0
    assert result["min_price"] == 10.0
    assert result["max_price"] == 0.0
    assert result["suggested_listing"] == 0.0


def test_get_market_valuation_falls_back_when_gemini_api_key_unset(monkeypatch):
    """`GEMINI_API_KEY` unset makes `_estimate_price` raise ValueError
    internally, which is caught by the broad except and routed to
    `_fallback_estimate_price` -- confirmed here by comparing against a
    direct call to that method with identical arguments."""
    monkeypatch.setattr("env.GEMINI_API_KEY", None)

    svc = MarketPriceService()
    expected = svc._fallback_estimate_price("gemini-less item", "good", "electronics")

    result = svc.get_market_valuation("gemini-less item", condition="good", category="electronics")

    assert result == expected
    assert result["source"] == "Estimation (Fallback)"


def test_get_market_valuation_falls_back_on_malformed_json(monkeypatch):
    """Content that never contains a well-formed `{...}` JSON object makes
    `json.loads` raise, which is caught by the broad except-clause and
    routed to `_fallback_estimate_price`."""
    fake_class, _, _ = _make_fake_chat_model("not valid json {broken")
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    expected = svc._fallback_estimate_price("broken response item", "fair", "toys")

    result = svc.get_market_valuation("broken response item", condition="fair", category="toys")

    assert result == expected
    assert result["source"] == "Estimation (Fallback)"


def test_get_market_valuation_falls_back_when_model_invoke_raises(monkeypatch):
    """Any exception raised while talking to the model (e.g. a network or
    SDK error) is caught by the broad except-clause and routed to
    `_fallback_estimate_price`."""
    from unittest.mock import MagicMock

    fake_grounded_model = MagicMock()
    fake_grounded_model.invoke.side_effect = RuntimeError("network is down")
    fake_model_instance = MagicMock()
    fake_model_instance.bind.return_value = fake_grounded_model
    fake_class = MagicMock(return_value=fake_model_instance)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", fake_class)

    svc = MarketPriceService()
    expected = svc._fallback_estimate_price("flaky item", "good", None)

    result = svc.get_market_valuation("flaky item", condition="good", category=None)

    assert result == expected
    assert result["source"] == "Estimation (Fallback)"


def test_get_market_valuation_default_condition_is_good(monkeypatch):
    """`get_market_valuation`'s `condition` parameter defaults to "good".
    Forces the Gemini path to fail deterministically (unset API key) so the
    result comes from `_fallback_estimate_price`, then checks the default
    propagated all the way through as `condition_used`."""
    monkeypatch.setattr("env.GEMINI_API_KEY", None)

    svc = MarketPriceService()
    result = svc.get_market_valuation("anything", category="other")

    assert result["source"] == "Estimation (Fallback)"
    assert result["condition_used"] == "good"
