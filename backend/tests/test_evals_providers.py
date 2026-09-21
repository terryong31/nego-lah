"""SPEC-083 — the eval harness has to be able to point at either engine.

`evals/runner.py` is coverage-omitted (it drives a real model, so it cannot run
in the suite), and that is exactly how it came to import `_gemini_model` — a
name `agent.llm_factory` had renamed to `_gemini_model_name` — and die at
runtime with nothing going red. The provider seam therefore lives in
`evals/providers.py`, which IS covered, and these tests hold it.

The property that matters most is S2: since SPEC-081 the prompt and the
temperature are both read from `current_provider`, so pointing the harness at
the local model without pinning that ContextVar would score the local model
under the CLOUD prompt — a configuration production never runs.
"""

import pytest

import domains.negotiation.bot as bot
from domains.negotiation.llm_factory import (
    PROVIDER_CLOUD,
    PROVIDER_LOCAL,
    cloud_provider_info,
    current_provider,
    local_provider_info,
)
from evals.providers import CHOICES, CLOUD, LOCAL, is_self_hosted, pinned_provider, resolve_provider

# ---------------------------------------------------------------------------
# S1 — name -> engine
# ---------------------------------------------------------------------------


def test_resolve_local():
    assert resolve_provider(LOCAL).provider == PROVIDER_LOCAL


def test_resolve_cloud():
    assert resolve_provider(CLOUD).provider == PROVIDER_CLOUD


def test_unknown_provider_raises_rather_than_defaulting():
    """Silently falling back to cloud would label a cloud run as a local one."""
    with pytest.raises(ValueError):
        resolve_provider("qwen-ish")


def test_choices_are_what_the_cli_offers():
    assert set(CHOICES) == {CLOUD, LOCAL}


# ---------------------------------------------------------------------------
# S2 — the whole SPEC-081 stack follows the pin, not just the model
# ---------------------------------------------------------------------------


def test_pinning_local_selects_the_local_prompt_and_temperature():
    with pinned_provider(resolve_provider(LOCAL)):
        info = current_provider.get()
        assert bot.customer_prompt_for(info) == bot.LOCAL_CUSTOMER_AGENT_PROMPT
        assert bot.customer_temperature_for(info) == bot.LOCAL_AGENT_TEMPERATURE


def test_pinning_cloud_selects_the_cloud_prompt_and_temperature():
    with pinned_provider(resolve_provider(CLOUD)):
        info = current_provider.get()
        assert bot.customer_prompt_for(info) == bot.CUSTOMER_AGENT_PROMPT
        assert bot.customer_temperature_for(info) == bot.CLOUD_AGENT_TEMPERATURE


# ---------------------------------------------------------------------------
# S3 — the pin is scoped, not sticky
# ---------------------------------------------------------------------------


def test_pin_restores_the_previous_provider():
    token = current_provider.set(cloud_provider_info())
    try:
        with pinned_provider(local_provider_info()):
            assert current_provider.get().is_local
        assert current_provider.get().provider == PROVIDER_CLOUD
    finally:
        current_provider.reset(token)


def test_pin_restores_even_when_the_run_raises():
    assert current_provider.get() is None
    with pytest.raises(RuntimeError):
        with pinned_provider(local_provider_info()):
            raise RuntimeError("scenario blew up")
    assert current_provider.get() is None


# ---------------------------------------------------------------------------
# S5 — cost reporting tells a self-hosted run from an unpriced one
# ---------------------------------------------------------------------------


def test_self_hosted_is_recognised():
    assert is_self_hosted(resolve_provider(LOCAL)) is True
    assert is_self_hosted(resolve_provider(CLOUD)) is False


# ---------------------------------------------------------------------------
# S5 — the rename that broke the harness
# ---------------------------------------------------------------------------


def test_the_name_the_runner_imports_still_exists():
    """`runner.main()` imported `_gemini_model`, which no longer existed. The
    import is inside the function, so collection passed and the harness only
    failed when someone actually ran it."""
    from domains.negotiation.llm_factory import _gemini_model_name

    assert isinstance(_gemini_model_name(), str)


def test_runner_imports_cleanly():
    """Guards the whole module against another rename landing unnoticed."""
    import evals.runner as runner

    assert callable(runner.main)
    assert callable(runner.report)
