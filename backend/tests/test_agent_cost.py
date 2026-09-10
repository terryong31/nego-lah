"""Turning token counts into money (SPEC-059).

TODO 45 asks for the agent to be *cheaper*, which means the cost has to be
computable before and after rather than asserted. `routes/chat.py` already
tracks tokens for the abuse budget, but with a `len(text)//4` estimate that is
fine for a ceiling and useless for a price. This reads the provider's own
`usage_metadata` instead.
"""

from types import SimpleNamespace

import pytest

from agent.cost import (
    MODEL_PRICING,
    TokenUsage,
    estimate_cost,
    usage_from_result,
)


def _ai_message(input_tokens=None, output_tokens=None):
    usage = (
        {"input_tokens": input_tokens, "output_tokens": output_tokens,
         "total_tokens": (input_tokens or 0) + (output_tokens or 0)}
        if input_tokens is not None else None
    )
    return SimpleNamespace(usage_metadata=usage)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def test_a_known_model_prices_its_tokens():
    model = next(iter(MODEL_PRICING))
    cost = estimate_cost(model, input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(MODEL_PRICING[model].input_per_mtok_rm)


def test_input_and_output_are_priced_separately():
    """Output tokens cost several times more than input on every provider; a
    single blended rate would misrank a verbose model against a terse one."""
    model = next(m for m, p in MODEL_PRICING.items()
                 if p.output_per_mtok_rm != p.input_per_mtok_rm)
    in_only = estimate_cost(model, 1_000_000, 0)
    out_only = estimate_cost(model, 0, 1_000_000)
    assert in_only != out_only


def test_an_unknown_model_returns_none_rather_than_a_made_up_number():
    """A wrong cost is worse than no cost — it would be reported as fact."""
    assert estimate_cost("some-model-we-have-never-priced", 1000, 1000) is None


def test_zero_tokens_cost_zero():
    model = next(iter(MODEL_PRICING))
    assert estimate_cost(model, 0, 0) == 0.0


def test_the_self_hosted_model_is_priced_at_zero_marginal_cost():
    """The M5 laptop's electricity is not a per-token charge, and pretending
    otherwise would make the hybrid router look worse than it is."""
    from agent.llm_factory import DEFAULT_LOCAL_MODEL

    assert estimate_cost(DEFAULT_LOCAL_MODEL, 1_000_000, 1_000_000) == 0.0


def test_every_priced_model_has_sane_numbers():
    for name, price in MODEL_PRICING.items():
        assert price.input_per_mtok_rm >= 0, name
        assert price.output_per_mtok_rm >= 0, name
        assert price.output_per_mtok_rm >= price.input_per_mtok_rm, (
            f"{name}: output is never cheaper than input"
        )


# ---------------------------------------------------------------------------
# Reading real usage off a LangGraph result
# ---------------------------------------------------------------------------

def test_usage_is_summed_across_every_llm_step_of_the_turn():
    """A ReAct turn is several model calls. Counting only the last one would
    under-report a tool-using turn by most of its cost."""
    result = {"messages": [
        _ai_message(1200, 40),
        _ai_message(1500, 90),
        _ai_message(1700, 120),
    ]}

    usage = usage_from_result(result)

    assert usage.input_tokens == 4400
    assert usage.output_tokens == 250
    assert usage.total_tokens == 4650


def test_messages_without_usage_metadata_are_skipped_not_counted_as_zero_failures():
    result = {"messages": [
        SimpleNamespace(content="a human turn"),
        _ai_message(100, 10),
        _ai_message(),
    ]}

    usage = usage_from_result(result)

    assert usage.input_tokens == 100
    assert usage.output_tokens == 10


def test_a_result_with_no_usage_at_all_reports_nothing_rather_than_lying():
    usage = usage_from_result({"messages": [SimpleNamespace(content="hi")]})
    assert usage == TokenUsage(0, 0)
    assert usage.is_empty


def test_a_malformed_result_does_not_take_the_turn_down():
    """Accounting is bookkeeping. It must never be the reason a buyer's turn fails."""
    assert usage_from_result(None).is_empty
    assert usage_from_result({}).is_empty
    assert usage_from_result({"messages": None}).is_empty
