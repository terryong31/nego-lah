# ADR 0022: A Message From the Future Is History, Not News

## Status
Accepted

## Context

The buyer opens the chat, reads the seller's reply, walks back to the
storefront and reloads — and the unread chip is on the avatar again. The
console had the mirror of it: "mark as read" cleared the dot until the next
list refresh brought it straight back.

Both watermarks were written correctly. `POST /chat/read` and
`POST /admin/chats/{id}/read` both stamp `datetime.now(UTC)`, and both counts
compare against `messages.created_at`. The column is a `timestamptz`. The
writer was not:

```python
'created_at': datetime.now().isoformat()   # naive — local time, no offset
```

Postgres parses a literal with no offset using the *session's* zone, which is
UTC on Supabase. So a message written at 18:33 in Kuala Lumpur was stored as
`18:33+00` — eight hours in the future, and `created_at > user_last_read_at`
stayed true for the whole UTC offset no matter how many times the buyer read
it. On a UTC host the bug is invisible, which is why it survived two specs
that were both about read state.

That is a one-word fix for messages written from here on. It does nothing for
the rows already in the table, which carry a skew nobody recorded: we know
neither which host wrote each row nor what its offset was that day. Rewriting
them would be guessing.

## Decision

**1. Every timestamp this backend writes is aware.** `datetime.now(UTC)` in
`add_message`, `items.create`/soft-delete, and pending-payment state. A naive
literal in a `timestamptz` column means "whatever zone the process happened to
be in", which is not a fact about the domain.

**2. Unread state believes nothing dated in the future.** `newest_at` and
`count_since` filter at `now + MESSAGE_FUTURE_GRACE` (one minute), and the
console's `_is_unread` applies the same test to the last customer message. Two
clocks that both think they are on UTC can disagree by a second; nothing
legitimate is a minute ahead. Past that horizon a row has not *just arrived* —
it is mis-stamped, and it is a message the reader has already seen. Excluding
it is not hiding data; it is declining to announce yesterday as news.

This is what heals the rows already in the table, and it is why the horizon
sits on the read side rather than in a migration. The tempting alternative —
stamp "read" at the newest row, wherever it happens to be dated — clears
today's chip and then silences the badge for every genuine message until the
wall clock catches up with the skew. Eight hours of swallowed notifications is
a worse bug than the stuck chip it replaces.

**3. A watermark covers the newest message it claims to have read.**
`read_watermark(user_id, role)` stamps `max(now, newest_at(user_id, role))`,
and both mark-as-read paths use it. `now` is this process's opinion of when the
newest message arrived; the row itself was dated by whoever wrote it. A mark
that stops a second short of the message it was meant to include is, again, a
chip that comes back after being read. The anchor's reach is bounded by the
horizon above — it can only ever move the mark forward by seconds — and it
never moves it backwards, so it cannot re-arm a badge for something already
read. `role` is whatever that side counts as unread ('ai' for the buyer's chip,
'human' for the console's dot), so the anchor and the count always read the
same rows.

**4. Leaving the conversation stamps it read, the same as arriving.** The
arrival stamp can only cover what was already there, and the agent's answer to
the buyer's own turn is written after it — over the chat page's own stream,
which never touches the notification stream, so nothing else moved the
watermark past it. Chat with the agent, walk away, reload, and a chip appears
for a message the buyer watched arrive. Navigating off `/chat`, or
backgrounding the tab while on it, now stamps.

Deliberately *not* stamped from the server at the end of a turn: SPEC-060 lets
a turn finish after the tab is gone, and a reply nobody was there for is
exactly the message the badge exists to announce.

## Consequences

- Timestamps written before this change stay skewed in the table. Reads that
  only *order* by them are unaffected (paging is by `id`), and unread state now
  steps around them. Anything that displays one — a listing's "created" date —
  is still off by the writing host's offset until the row is rewritten.
- Genuinely new messages are never hidden by the horizon unless this process's
  clock runs more than a minute behind the one that wrote the row, which NTP
  makes a non-event. If it ever happened, the failure is a badge that arrives a
  minute late, not one that never arrives.
- `read_watermark` costs one indexed lookup per mark-as-read. Marking read is a
  human action, not a hot path.
- A future writer that reintroduces a naive timestamp will not resurrect the
  stuck chip — the horizon absorbs it. It will surface instead as a message
  that never badges, which is the failure mode we would rather debug.
