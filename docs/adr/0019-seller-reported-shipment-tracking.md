# ADR 0019: Seller-Reported Shipment Tracking

## Status
Accepted

## Context

The order lifecycle had no ending. `orders.status` could be moved to `shipped`, but there
was nowhere to record what it shipped *with*, so "shipped" was a word rather than something
a buyer could act on. In practice the seller pasted tracking numbers into the chat by hand,
and the agent — asked "where's my stuff?" — could only repeat the status back.

That hand-pasting is the real failure mode. It is a step performed from memory, after the
step that actually mattered (handing the parcel over), by someone who is doing this between
other jobs. It gets skipped, and the buyer is left watching an order that says "confirmed"
while their parcel is already in transit.

## Decision

**One act, three notifications.** `PUT {ADMIN_PREFIX}/orders/{order_id}/shipment` records
courier and tracking number, stamps `shipped_at`, moves the order to `shipped`, emails the
buyer, and posts into their chat — where it also rings the SSE notification bell. The
seller does the one thing they were going to do anyway; everything else follows from it.
`notify: false` exists for correcting a shipment the buyer has already been told about.

**The write comes first, and notifications are individually best-effort.** An order that
shipped but whose email bounced is a recoverable annoyance. An email announcing a shipment
that was never recorded is a lie the seller cannot retract. The response reports what
actually went out (`notified: {email, chat}`) and the console shows a *warning*, not a
success, when the record saved but the buyer was not reached — otherwise the seller assumes
the buyer knows and nobody chases it.

**Seller as source of truth; no carrier APIs.** `domains/catalog/shipping.py` is a lookup
table mapping the Malaysian carriers this store uses to a tracking URL template, plus the
spellings a seller in a hurry actually types (`jnt`, `j&t`, `poslaju`). For a single seller
posting a few parcels a week, a table that occasionally needs a new row is a far smaller
liability than a set of integrations that can rate-limit, expire, or change shape. The table
is allowed to miss: an unknown carrier is still recorded, it just yields no link.

**One source of buyer-facing wording.** `services/shipping_notice.py` assembles the facts;
the email template, the chat message and the agent's answer all render from it. The buyer
receives all three, so three call sites composing their own sentences is three chances to
describe different shipments to the one person positioned to notice.

**No new agent tool.** Tracking is folded into `check_user_orders`. "Where's my stuff?" is
the question that tool already exists to answer, and every additional tool costs its schema
in every prompt of every turn — the opposite direction from SPEC-058. `_tracking_lines`
emits nothing rather than `Courier: None`, because a model handed "None" will read it out.

**The chat message is plain text with a bare URL.** Never markdown. `chatBlocks.ts` lifts
`[label](https://…)` out of an assistant message and renders it as a payment card, so a
markdown tracking link would arrive under a "Secured by Stripe" badge — the exact thing
SPEC-056 #4 hardened against, except self-inflicted.

## Consequences

- **Additive schema only.** Five nullable columns. Existing orders are untouched, and every
  read path treats NULL as "not shipped yet" — which is what it already did implicitly.
- **`delivered` becomes an event, not just a value.** Only a *transition* into it stamps
  `delivered_at` and notifies; re-saving an already-delivered row (which the console does
  whenever the seller re-picks the same value) sends nothing.
- **Courier names are normalised on write.** `jnt` is stored as `J&T Express`, so the buyer
  reads a carrier name rather than the seller's shorthand, and the tracking URL resolves.
- **A tracking number can still be wrong.** Nothing validates the code against the carrier;
  a typo produces a link to a carrier page that finds nothing. `notify: false` plus a
  re-submit is the correction path.
- **TODO 49 and 50 close together.** 50 ("AI updates the user about shipping status") was
  not implementable without 49's data, so building the AI half alone would have shipped a
  tool that could only say "shipped".

## Alternatives Considered

- **Carrier API integration.** Rejected for this scale — see above. The registry is the
  cheap 90% of the value.
- **A dedicated `check_shipping_status` agent tool.** Rejected: a second tool answering the
  same question splits the model's choice, doubles the chance it picks wrong, and adds a
  schema to every turn.
- **Notify from a background worker.** Rejected as premature. Two best-effort calls behind
  a write the seller is watching complete is not worth a queue; if Resend latency becomes
  visible in the console, the digest sweeper (SPEC-052) is the pattern to copy.
- **Blocking the response on notification success.** Rejected: it inverts the priority. The
  record is what must not be lost.

## References
- `specs/SPEC-057-postage-and-shipment-tracking.md`
- ADR 0016 (buffered notification digests) — the same "tell the buyer once, properly" instinct
- ADR 0018 / SPEC-056 #1 — why the endpoint lives on the CSRF-protected admin router
