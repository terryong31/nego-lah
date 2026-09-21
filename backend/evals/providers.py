"""Which engine an eval run is pointed at (SPEC-083).

Pointing the harness at the self-hosted model is not an env flip. Since SPEC-081
the system prompt AND the sampling temperature are both resolved per turn from
`llm_factory.current_provider`, so setting `LLM_PROVIDER=local` and nothing else
would run the local *model* under the CLOUD prompt at the CLOUD temperature —
scoring a configuration production never serves.

`pinned_provider` sets that ContextVar for the whole run instead, which also
means the run bypasses the health probe and the concurrency lease: a busy laptop
cannot silently move half the scenarios to Gemini and turn a comparison into an
average of two different agents.

This lives here, and not in `runner.py`, because `runner.py` is coverage-omitted
— it drives a real model — and that is precisely how it came to import a name
`agent.llm_factory` had renamed, and fail only when someone ran it.
"""

from contextlib import contextmanager

from domains.negotiation.llm_factory import (
    ProviderInfo,
    cloud_provider_info,
    current_provider,
    local_provider_info,
)

CLOUD = "cloud"
LOCAL = "local"
CHOICES = (CLOUD, LOCAL)

_RESOLVERS = {
    CLOUD: cloud_provider_info,
    LOCAL: local_provider_info,
}


def resolve_provider(name: str) -> ProviderInfo:
    """The engine named on the command line.

    Raises on an unknown name rather than falling back to cloud: a typo that
    quietly produced a cloud run would be reported under a local heading, which
    is worse than not running at all.
    """
    try:
        return _RESOLVERS[name]()
    except KeyError:
        raise ValueError(f"unknown provider {name!r} — expected one of {', '.join(CHOICES)}") from None


@contextmanager
def pinned_provider(info: ProviderInfo):
    """Serve every turn of the run from `info`, then put the ContextVar back.

    Mirrors what `hybrid_llm_session()` does for a real chat turn, minus the
    probe and the lease — an eval wants a fixed engine, not a routing decision.
    """
    token = current_provider.set(info)
    try:
        yield info
    finally:
        current_provider.reset(token)


def is_self_hosted(info: ProviderInfo) -> bool:
    """Whether this run has no per-token price, as opposed to an unknown one.

    `MODEL_PRICING` returning None means "we never priced this model". For the
    M5 that is not a gap in the table — there is no per-token price to look up,
    and reporting it as unknown invites someone to go find it.
    """
    return info.is_local
