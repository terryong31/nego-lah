---
id: SPEC-088
title: Payment Links Must Be Server-Issued
status: complete
priority: high
created: 2026-09-15
tags: [security, payment, agent, chat]
assigned: agent
---

# Context & Objectives

SPEC-056 #4 stopped the agent from badging an arbitrary URL as a checkout by allowlisting the
**host**: only `buy.stripe.com` and `checkout.stripe.com` may be dressed in a PayCard — the
"Deal Agreed / Secured by Stripe" tile, the strongest trust signal the product has.

The host is not the only part a model can invent. Observed in a real conversation, with the
tool trace (SPEC-087) proving no tool ran:

```
[ai] tool_calls=None
"RM2500? That's very close to my listed price of RM2599! 😊
 Let me check if we can make this work...
 [Pay RM2500 Now](https://checkout.stripe.com/pay/5bf2b193-…-a03d6dd44193?price=2500)"
```

`create_checkout_link` was never called, no Stripe session exists, and the path is the
**item's own UUID** with a `?price=` the model chose. The host is genuine, so it passed the
allowlist and rendered as a PayCard. The buyer is shown a branded, "Secured by Stripe"
payment tile pointing at a URL that does not exist.

Two things are wrong and only one is about the model. A model will sometimes fabricate;
the app must not be able to present a fabrication as a payment. The server knows exactly
which URL it issued — `payment_state.get_pending_payment(user_id, item_id)` holds it — and
never checked the agent's text against it.

**Objective:** a payment URL reaches the buyer only if this server issued it for this buyer
and this item.

# Acceptance Criteria

- [x] **Server-authoritative:** a markdown link whose URL is not one this server issued for
      this `(user_id, item_id)` is stripped from the agent's text.
- [x] **Fail-closed:** no pending payment for the pair means every payment-shaped link is
      stripped — including one on a trusted host.
- [x] **Both paths:** `chat()` and `chat_stream()` both sanitise, so live and replayed
      transcripts agree.
- [x] **Nothing leaks mid-stream:** a link is held back until it is complete enough to
      validate; the buyer never sees a fabricated URL flash past before it is removed.
- [x] **Ordinary links untouched:** non-payment markdown and plain prose stream unchanged.
- [x] **Persisted clean:** the stripped text is what goes into `messages`, so a reload cannot
      resurrect the fake link.
- [x] **Visible, not silent:** the stripped link is replaced by a short line telling the buyer
      no payment link was created, rather than vanishing into a sentence that still says
      "here's your link".

# Technical Design & Contracts

```python
# agent/link_guard.py
PAY_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")

def issued_payment_urls(user_id, item_id) -> set[str]      # from payment_state
def sanitize_payment_links(text, user_id, item_id) -> str
def split_safe_prefix(buffer) -> tuple[str, str]           # streaming: (emit, hold)
```

Invariant: text leaves the backend containing a payment URL only if that exact URL is in
`issued_payment_urls(...)`.

# TDD Scenarios

- [x] **S1:** the observed fabricated URL (trusted host, item UUID path) is stripped.
- [x] **S2:** the real issued URL survives verbatim.
- [x] **S3:** no pending payment -> every payment-shaped link is stripped.
- [x] **S4:** a link to an untrusted host is stripped too.
- [x] **S5:** prose with no links is returned byte-identical.
- [x] **S6:** `split_safe_prefix` never emits a partially-written link.
- [x] **S7:** a stream containing a fabricated link yields no fragment of that URL.
- [x] **S8:** a Redis failure strips rather than trusts.

# Implementation Files

- `backend/agent/link_guard.py`
- `backend/agent/bot.py`
- `backend/tests/test_payment_link_guard.py`
