# ADR 0018: Pre-Launch Security Remediation — Trust Boundaries an Audit Found Open

## Status
Accepted

## Context

A second full-stack audit five days before launch raised eight findings. All eight were
re-verified against the source before anything was changed, and two of the reported HIGHs
turned out to be blunted by controls the report had not accounted for. Recording that
here matters as much as the fixes: a severity table nobody checked is how a team spends
launch week on the wrong thing.

**Where the report and the code disagreed**

- *Refund CSRF (reported HIGH).* Real gap, lower severity. `admin_sid` is `SameSite=Lax`,
  which does not accompany a cross-site form POST, and `CORSMiddleware` refuses the
  credentialed `fetch` alternative. The bug is a **broken invariant** — every other
  mutating admin route is CSRF-gated and the one that moves money was not — rather than a
  live exploit. Fixed anyway, at the cost of one moved function: an invariant with one
  exception is not an invariant, and the next person to add a route near it will copy
  whichever pattern they land on.
- *Chunked-transfer DoS (reported MEDIUM).* Real, and the report understated the
  mechanism. Rejecting `Transfer-Encoding: chunked` — its recommendation — leaves the
  larger hole open: a *lying* `Content-Length` bypasses a header check just as well.
- *Token in query string (reported MEDIUM).* Real. Held at MEDIUM.

**Where the report was exactly right**

`collect_shipping_info` scoped its update to `buyer_id` only `if user_id:` — SPEC-051
shipped the filter but left it optional, so an unidentified caller rewrote the recipient,
phone and address of any order by id. `PUT /user/{id}/email` took no password and passed
`email_confirm: True`, making a stolen access token a permanent account takeover. And
`PAY_LINK` promoted any `https://` markdown link to a tile reading "Deal Agreed" over a
"Secured by Stripe" badge — chosen by a model that reads buyer text.

## Decision

1. **Refunds move to the CSRF-protected router.** `POST /payment/refund/{item_id}` becomes
   `POST {ADMIN_PREFIX}/orders/refund/{item_id}` in `routes/admin/orders.py`, inheriting
   `verify_admin` + `verify_csrf_token` from the `protected` router, and writes an audit
   entry like every other order mutation. Moving it beats adding the dependency inline:
   the router is the thing people remember, a per-route dependency is the thing they
   forget.

2. **Agent tools fail closed.** `collect_shipping_info` refuses before building a query
   when `get_user_id()` is falsy, and the `buyer_id` filter is unconditional. This matches
   `check_user_orders`, which had it right all along.

3. **Identity operations cost the password.** `_reauthenticate` gates both the email
   change and account deletion. The email change additionally runs on the **user's own
   session** rather than the admin API, which is what makes Supabase mail the confirmation
   link; the address does not move until someone clicks it. Merely dropping
   `email_confirm: True` — the report's suggestion — would have left the account holding
   an unverified address with nobody informed, which is worse than what it replaced.

4. **Re-authentication gets its own client.** `connector.new_user_client()` returns a fresh
   anon client per request. `user_supabase` is a module-level singleton, so signing in on
   it writes the session into shared state; harmless when the sign-in is only a password
   *check*, and a cross-account write when the request then acts as the user. The obvious
   implementation of decision 3 walks straight into this, so the singleton is no longer
   imported by `routes/user.py` at all, and a test asserts its absence.

5. **Brute-force throttling keys on the account, not the address.** `check_rate_limit`
   on `reauth:{user_id}`, ten attempts per fifteen minutes. Password guessing is an attack
   on one account from anywhere, so a per-IP counter is the wrong axis in both directions:
   a rotating proxy sails through it, and one NAT address is a whole venue — which is
   precisely why `limiter.py`'s ceilings are sized in the thousands. The per-IP
   `ACCOUNT_LIMIT` stays as the coarse "one scripted laptop" backstop.

6. **The frontend decides what looks first-party.** `isTrustedPaymentUrl` admits only
   `buy.stripe.com` and `checkout.stripe.com` (exact host or subdomain, https only),
   parsed with `URL` rather than matched with a regex — every classic bypass is a string
   that *contains* a trusted name while resolving elsewhere. An untrusted link renders as
   the raw markdown it was: visibly not a checkout, and nothing silently disappears.

7. **The request body is metered, not merely declared.** `RequestDefenseMiddleware` becomes
   a raw ASGI middleware so it can wrap `receive` and count `http.request` bytes as they
   arrive, returning `http.disconnect` past the ceiling and answering 413 on the
   `ClientDisconnect` that produces. `BaseHTTPMiddleware` cannot do this: it hands you a
   finished `Request`, by which point the bytes are already in RAM. The `Content-Length`
   check is kept in front of it, because refusing an honest oversized request before
   reading anything is still cheaper.

8. **SSE is authorised by a ticket.** `POST /chat/notifications/ticket` is a normal
   header-authenticated request that mints a 30-second, single-use ticket (`GETDEL`, so two
   connections racing on a leaked ticket cannot both win). The stream takes `?ticket=` and
   no longer accepts `?token=`; `get_optional_user_id` stops reading it too.

9. **One source of Supabase clients.** `core/database.py` owns the asyncpg pool and nothing
   else; the duplicate PostgREST clients it built at import — keyed
   `USER_SUPABASE_KEY or ADMIN_SUPABASE_KEY`, the fallback SPEC-051 removed from `env.py` —
   are gone, along with the same fallback in `core/config.py`.

## Consequences

- **Breaking, deliberately.** Changing an email now returns
  `{"confirmation_required": true}` and does not take effect until the link is clicked;
  deleting an account requires a body carrying `current_password`. Both are user-visible
  and both are the point.
- **`useApi` grew a `reauth` flag.** Its 401 handler signs the user out, which is right for
  a dead session and wrong for "that password was incorrect" — without the flag, mistyping
  your password on the profile page would log you out of a session that was never in
  doubt. This bug already existed for password changes; the audit's fixes would have
  spread it to two more forms.
- **The SSE stream now costs a round trip to open.** Once per session, on a path that
  already awaited `getSession()`.
- **Chunked uploads are supported, not blocked.** The cap is on bytes, so a legitimate
  streamed upload under the ceiling arrives intact — a plain `Transfer-Encoding` rejection
  would have broken those.
- **Anti-patterns are written down.** `docs/SECURITY_ANTI_PATTERNS.md` carries each of
  these as BAD/GOOD pairs plus an index of where enforcement actually lives, and `AGENTS.md`
  rule 6 points at it. (That link was committed as an absolute `file:///Users/...` path in
  a public repository; it is now repo-relative.)

## Alternatives Considered

- **Add `Depends(verify_csrf_token)` to the refund route in place.** Rejected: leaves a
  second pattern for admin mutations, which is the condition that produced the bug.
- **Reject `Transfer-Encoding: chunked` outright.** Rejected: does not address an
  under-declared `Content-Length`, and breaks legitimate streamed uploads.
- **Keep `?token=` and document it as accepted risk.** Rejected. The ticket is ~50 lines
  and removes the credential from every log that will exist on launch day.
- **Scrub untrusted links server-side before persisting them.** Deferred. The badge is
  what carries the trust and the badge is now gated; a backend scrub would be defence in
  depth, not the fix, and launch week is the wrong time to add a rewrite step to the
  transcript.

## References
- `specs/SPEC-056-pre-launch-security-remediation.md`
- `docs/SECURITY_ANTI_PATTERNS.md`
- ADR 0015 (SPEC-051), whose optional-scoping fix this supersedes with a fail-closed one
