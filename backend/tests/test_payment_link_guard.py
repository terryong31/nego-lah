"""SPEC-088 — a payment link reaches the buyer only if this server issued it.

SPEC-056 #4 allowlisted the host a PayCard may point at. A model can invent more
than a host. Observed in production, with the SPEC-087 trace proving no tool ran:

    [Pay RM2500 Now](https://checkout.stripe.com/pay/<the item's own uuid>?price=2500)

`checkout.stripe.com` is genuine, so it passed the allowlist and rendered as the
"Deal Agreed / Secured by Stripe" tile — over a URL that does not exist.
"""

from unittest.mock import patch

import pytest

from agent.link_guard import (
    PAY_LINK_RE,
    STRIPPED_NOTICE,
    issued_payment_urls,
    sanitize_payment_links,
    split_safe_prefix,
)

USER, ITEM = "buyer-1", "5bf2b193-912d-42eb-bcca-a03d6dd44193"
REAL = "https://buy.stripe.com/test_00g5kQ1234abcd"
# The exact shape the model invented: trusted host, the item's own id as a path.
FABRICATED = f"https://checkout.stripe.com/pay/{ITEM}?price=2500"


def _issued(urls):
    return patch("agent.link_guard.issued_payment_urls", lambda _u, _i: set(urls))


# ---------------------------------------------------------------------------
# S1-S4 — what survives
# ---------------------------------------------------------------------------

def test_the_fabricated_link_is_stripped():
    text = f"RM2500? 😊\n\n[Pay RM2500 Now]({FABRICATED})\n\nOnce you pay I'll ship it."

    with _issued([]):
        out = sanitize_payment_links(text, USER, ITEM)

    assert FABRICATED not in out
    assert "checkout.stripe.com" not in out
    assert STRIPPED_NOTICE in out


def test_the_real_issued_link_survives_verbatim():
    text = f"Great! [Pay RM2500 Now]({REAL})"

    with _issued([REAL]):
        assert sanitize_payment_links(text, USER, ITEM) == text


def test_a_trusted_host_is_not_enough_on_its_own():
    """The whole point: the host was genuine and the URL was still invented."""
    text = f"[Pay now]({FABRICATED})"

    with _issued([REAL]):
        assert FABRICATED not in sanitize_payment_links(text, USER, ITEM)


def test_an_untrusted_host_is_stripped_too():
    evil = "https://checkout.stripe.com.evil.test/pay/123"
    with _issued([REAL]):
        assert evil not in sanitize_payment_links(f"[Pay]({evil})", USER, ITEM)


def test_prose_without_links_is_untouched():
    text = "RM2500 is close! What do you say?\n\nStill interested?"
    with _issued([]):
        assert sanitize_payment_links(text, USER, ITEM) == text


def test_every_link_in_a_message_is_judged_separately():
    text = f"[real]({REAL}) and [fake]({FABRICATED})"
    with _issued([REAL]):
        out = sanitize_payment_links(text, USER, ITEM)

    assert REAL in out
    assert FABRICATED not in out


# ---------------------------------------------------------------------------
# S3/S8 — fail closed
# ---------------------------------------------------------------------------

def test_no_pending_payment_strips_everything():
    with patch("payment.payment_state.get_pending_payment", lambda *a: None), \
         patch("payment.payment_state.get_active_payments_for_user", lambda *a: []):
        out = sanitize_payment_links(f"[Pay]({FABRICATED})", USER, ITEM)

    assert FABRICATED not in out


def test_a_lookup_failure_strips_rather_than_trusts():
    def boom(*_a, **_kw):
        raise RuntimeError("redis down")

    with patch("payment.payment_state.get_pending_payment", boom):
        assert issued_payment_urls(USER, ITEM) == set()
        assert REAL not in sanitize_payment_links(f"[Pay]({REAL})", USER, ITEM)


def test_an_anonymous_turn_has_no_issued_links():
    assert issued_payment_urls(None, ITEM) == set()


# ---------------------------------------------------------------------------
# S6 — the streaming split never lets a half-written URL out
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("partial", [
    "Here you go [Pay RM2500",
    "Here you go [Pay RM2500 Now](https://checkout.stri",
    "Here you go [",
])
def test_an_unclosed_link_is_held_back(partial):
    emit, hold = split_safe_prefix(partial)

    assert "[" not in emit
    assert hold.startswith("[")
    assert emit + hold == partial


def test_a_closed_link_is_released_for_judging():
    buf = f"Here you go [Pay RM2500 Now]({REAL})"
    emit, hold = split_safe_prefix(buf)

    assert emit == buf
    assert hold == ""


def test_plain_text_is_never_held():
    assert split_safe_prefix("no links here") == ("no links here", "")


# ---------------------------------------------------------------------------
# S7 — nothing of a fabricated URL survives a stream, in any chunking
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size", [1, 3, 7, 40], ids=["char", "tiny", "small", "chunky"])
def test_no_fragment_of_a_fabricated_url_is_ever_emitted(size):
    full = f"RM2500? 😊\n\n[Pay RM2500 Now]({FABRICATED})\n\nOnce you pay I'll ship it."
    chunks = [full[i:i + size] for i in range(0, len(full), size)]

    emitted = []
    buffer = ""
    with _issued([]):
        for chunk in chunks:
            buffer += chunk
            safe, buffer = split_safe_prefix(buffer)
            if safe:
                emitted.append(sanitize_payment_links(safe, USER, ITEM))
        if buffer:
            emitted.append(sanitize_payment_links(buffer, USER, ITEM))

    out = "".join(emitted)
    assert "checkout.stripe.com" not in out
    assert "stripe" not in out.lower()
    assert "RM2500? 😊" in out, "the rest of the message still has to arrive"


def test_the_regex_matches_what_the_frontend_looks_for():
    """`chatBlocks.ts` badges on this shape; the guard has to judge the same one."""
    assert PAY_LINK_RE.search(f"[Pay RM50 Now]({REAL})")


# ---------------------------------------------------------------------------
# The real stream path, not just the helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_stream_never_yields_a_fabricated_link(monkeypatch):
    """Drives `bot.chat_stream` with the exact message the model produced."""
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessageChunk

    import agent.bot as bot

    full = f"RM2500? 😊\n\nLet me check...\n\n[Pay RM2500 Now]({FABRICATED})\n\nOnce you pay I'll ship it."

    class FakeAgent:
        async def astream(self, _payload, stream_mode="messages"):
            for i in range(0, len(full), 5):
                yield AIMessageChunk(content=full[i:i + 5]), {}

    fake_memory = MagicMock()
    fake_memory.get_history.return_value = []
    monkeypatch.setattr(bot, "conversation_memory", fake_memory)
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: FakeAgent())
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda _i: None)
    monkeypatch.setattr("agent.link_guard.issued_payment_urls", lambda _u, _i: set())

    emitted = [c for c in [x async for x in bot.chat_stream(USER, "2500?", item_id=ITEM)]
               if isinstance(c, str)]
    out = "".join(emitted)

    assert "checkout.stripe.com" not in out
    assert ITEM not in out
    assert "RM2500? 😊" in out

    # And the transcript is stored clean, so a reload cannot resurrect it.
    stored = fake_memory.add_message.call_args_list[-1][0][2]
    assert "checkout.stripe.com" not in stored


@pytest.mark.asyncio
async def test_chat_stream_passes_a_real_issued_link_through(monkeypatch):
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessageChunk

    import agent.bot as bot

    full = f"Great! 😊\n\n[Pay RM2500 Now]({REAL})"

    class FakeAgent:
        async def astream(self, _payload, stream_mode="messages"):
            for i in range(0, len(full), 5):
                yield AIMessageChunk(content=full[i:i + 5]), {}

    fake_memory = MagicMock()
    fake_memory.get_history.return_value = []
    monkeypatch.setattr(bot, "conversation_memory", fake_memory)
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: FakeAgent())
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda _i: None)
    monkeypatch.setattr("agent.link_guard.issued_payment_urls", lambda _u, _i: {REAL})

    out = "".join(c for c in [x async for x in bot.chat_stream(USER, "2500?", item_id=ITEM)]
                  if isinstance(c, str))

    assert REAL in out
