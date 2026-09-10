"""What a turn actually cost (SPEC-059).

`routes/chat.py` already counts tokens, but with a `len(text) // 4` estimate.
That is the right tool for the abuse ceiling it guards — cheap, never wrong in
the dangerous direction — and the wrong tool for a price, because it cannot see
the system prompt, the tool schemas, the replayed history, or the several model
calls a single ReAct turn makes.

This module reads the provider's own `usage_metadata` instead, which is the only
number that matches the invoice, and prices it. It exists so that "the agent is
cheaper now" can be a measurement rather than a claim.

Prices are per million tokens, in RM, and they WILL go stale — providers change
them. `PRICES_SOURCED` records when they were last checked; the eval harness
prints it alongside every result so nobody quotes a two-year-old number as
today's cost. An unpriced model returns None rather than a guess.
"""

import os
from dataclasses import dataclass

# When the numbers below were last checked against the providers' pricing pages.
# Printed with every cost report — see the module docstring.
PRICES_SOURCED = "2026-09-10"

# Providers quote USD. One conversion constant, overridable, so a currency move
# does not mean editing every row.
USD_TO_RM = float(os.getenv("USD_TO_RM", "4.20"))


@dataclass(frozen=True)
class ModelPrice:
    """Per-million-token prices, already converted to RM."""

    input_per_mtok_rm: float
    output_per_mtok_rm: float
    note: str = ""


def _usd(input_per_mtok: float, output_per_mtok: float, note: str = "") -> ModelPrice:
    return ModelPrice(
        input_per_mtok_rm=input_per_mtok * USD_TO_RM,
        output_per_mtok_rm=output_per_mtok * USD_TO_RM,
        note=note,
    )


# VERIFY BEFORE QUOTING. Only `gemini-3.8-flash` is a model id this codebase
# actually uses (agent/llm_factory.DEFAULT_GEMINI_MODEL). The other two rows were
# added so the eval harness has something to compare against, and BOTH their ids
# and their rates need checking against Google's pricing page before any decision
# rests on them — an id that does not exist will simply fail at call time, but a
# wrong RATE will quietly produce a confident, wrong comparison.
MODEL_PRICING: dict[str, ModelPrice] = {
    # Cloud overflow. Output is several times input on every provider, which is
    # why they are priced separately: a blended rate would rank a terse model
    # and a verbose one the same way.
    "gemini-3.8-flash": _usd(0.30, 2.50, "cloud overflow default"),
    "gemini-3.8-flash-lite": _usd(0.10, 0.40, "UNVERIFIED id + rate — check before relying on it"),
    "gemini-3.8-pro": _usd(1.25, 10.00, "UNVERIFIED id + rate — check before relying on it"),

    # Self-hosted. Zero MARGINAL cost per token: the laptop's electricity is a
    # fixed background cost, not a charge that scales with tokens, and pricing
    # it per token would make the hybrid router (SPEC-020) look worse than it is
    # for exactly the traffic it was built to absorb.
    "mlx-community/Qwen3.6-35B-A3B-4bit": ModelPrice(0.0, 0.0, "self-hosted M5 — no per-token cost"),
}


@dataclass(frozen=True)
class TokenUsage:
    """Real token counts for one agent turn, summed across its LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def is_empty(self) -> bool:
        """True when the provider told us nothing — report that, don't imply zero cost."""
        return self.total_tokens == 0


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of a turn in RM, or None if we have never priced this model.

    None on purpose. A wrong cost is worse than a missing one, because it gets
    reported as fact and compared against other wrong costs.
    """
    price = MODEL_PRICING.get(model)
    if price is None:
        return None
    return (
        input_tokens * price.input_per_mtok_rm
        + output_tokens * price.output_per_mtok_rm
    ) / 1_000_000


def usage_from_result(result) -> TokenUsage:
    """Sum `usage_metadata` across every model message in a LangGraph result.

    A ReAct turn is several model calls — decide, call a tool, read the result,
    answer — so reading only the final message would under-report a tool-using
    turn by most of its cost, which is precisely the kind of turn worth
    measuring.

    Never raises. This is bookkeeping; it must not be the reason a buyer's turn
    fails, so a malformed result reports nothing instead.
    """
    try:
        messages = (result or {}).get("messages") or []
    except AttributeError:
        return TokenUsage()

    total_in = total_out = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            continue
        total_in += usage.get("input_tokens") or 0
        total_out += usage.get("output_tokens") or 0

    return TokenUsage(total_in, total_out)
