# Security Anti-Patterns & Safe Coding Standards

This document catalogues real vulnerabilities and security anti-patterns discovered across the **Nego-Lah** monorepo during pre-production penetration testing and code auditing.

All autonomous AI agents and engineers working on this repository **MUST** consult and adhere to these guidelines to prevent introducing security flaws, authorization bypasses, or data leakage vectors.

---

## 1. Authentication & Authorization Anti-Patterns

### Anti-Pattern 1.1: Placing State-Changing Admin Endpoints Outside CSRF Protection
- **Flaw:** Admin authentication uses an `httpOnly` session cookie (`admin_sid`, `SameSite=Lax`). Mutating endpoints outside the protected router do not enforce `verify_csrf_token`.
- **Bad Practice Example:**
  ```python
  # BAD: Admin action on an unprotected router without verify_csrf_token
  @router.post("/payment/refund/{item_id}")
  def refund_item(item_id: str, admin: dict = Depends(verify_admin)):
      ...
  ```
- **Consequence:** An attacker can trigger Cross-Site Request Forgery (CSRF) via top-level requests or cross-origin submissions if an admin visits a malicious site while logged into the console.
- **Good Practice:**
  - ALL admin actions (especially financial or mutating actions like refunds) MUST reside in `routes/admin/` or explicitly include `Depends(verify_csrf_token)`:
  ```python
  # GOOD: Placed under routes/admin/ (which inherits verify_csrf_token) or explicit dependency
  @router.post("/orders/{order_id}/refund", dependencies=[Depends(verify_csrf_token)])
  def refund_order(order_id: str, admin: dict = Depends(verify_admin)):
      ...
  ```

---

### Anti-Pattern 1.2: Optional User Scoping in Service-Role Operations (IDOR / Fail-Open)
- **Flaw:** Making user ownership check optional (`if user_id: query = query.eq('buyer_id', user_id)`).
- **Bad Practice Example:**
  ```python
  # BAD: Fails open if user_id is None / unauthenticated
  user_id = get_user_id()
  query = admin_supabase.table('orders').update({...}).eq('id', order_id)
  if user_id:
      query = query.eq('buyer_id', user_id)
  result = query.execute()
  ```
- **Consequence:** If `user_id` is None, missing, or unpopulated in request context, the filter is skipped. The query updates ANY user's order by ID, leading to an Insecure Direct Object Reference (IDOR) and unauthorized data mutation.
- **Good Practice:**
  - Fail closed immediately if `user_id` is missing:
  ```python
  # GOOD: Strict fail-closed verification
  user_id = get_user_id()
  if not user_id:
      return "ERROR: Cannot proceed - user not identified. Please ensure you are logged in."

  result = (
      admin_supabase.table('orders')
      .update({...})
      .eq('id', order_id)
      .eq('buyer_id', user_id)
      .execute()
  )
  ```

---

### Anti-Pattern 1.3: Sensitive Account Mutation Without Re-Authentication
- **Flaw:** Allowing immediate account email replacement (`email_confirm: True`) or account deletion without verifying the user's current password.
- **Bad Practice Example:**
  ```python
  # BAD: Direct email change without current password check
  @router.put("/user/{user_id}/email")
  def change_email(user_id: str, payload: EmailUpdateSchema, token_user_id: str = Depends(verify_user_token)):
      get_user_id_from_body_or_token(user_id, token_user_id)
      admin_supabase.auth.admin.update_user_by_id(user_id, {"email": payload.new_email, "email_confirm": True})
  ```
- **Consequence:** If an attacker gets access to a temporary session token (via XSS, device theft, or network snooping), they can instantly change the email and take over the account permanently without knowing the password.
- **Good Practice:**
  - Require `current_password` before changing the email or deleting the account (`routes/user._reauthenticate`).
  - Drop `email_confirm: True` and run the update on the *user's own session* (`session.auth.update_user({"email": ...})`), which is what makes Supabase send the confirmation link. On the admin API, `email_confirm: True` marks the new address verified with no mail to either party — so "removing it" alone would leave the account with an unverified address and nobody told.
- **Do NOT re-authenticate on the shared client.** `connector.user_supabase` is a module-level singleton, so `sign_in_with_password` on it writes the session into state every concurrent request shares:
  ```python
  # BAD: two people re-authenticating at once race; whoever lands second owns the
  # client, and an operation that then acts AS the user acts as somebody else.
  user_supabase.auth.sign_in_with_password({"email": email, "password": pw})
  user_supabase.auth.update_user({"email": new_email})   # whose account?

  # GOOD: a client for this request only.
  session = new_user_client()
  session.auth.sign_in_with_password({"email": email, "password": pw})
  session.auth.update_user({"email": new_email})
  ```

---

### Anti-Pattern 1.5: Rate-Limiting a Credential Check by IP Address
- **Flaw:** Defending a password check with a per-IP limiter (`slowapi`, keyed on `get_remote_address`).
- **Consequence:** Wrong axis, twice over. Guessing a password is an attack on **one account** mounted from wherever the attacker likes, so a botnet or a rotating proxy sails straight through; meanwhile one NAT address is a whole conference, office or campus, so the limit punishes a roomful of people for nobody's mistake. This codebase sizes every per-IP ceiling for that reality (`limiter.py`), which makes them useless as brute-force defence by design.
- **Good Practice:**
  - Count failures against the **account being attacked**, with `cache.check_rate_limit(f"reauth:{user_id}", ...)`. Keep the per-IP ceiling as the coarse "one scripted laptop" backstop, not as the credential guard.

---

### Anti-Pattern 1.4: Passing Authentication Tokens in URL Query Strings
- **Flaw:** Accepting bearer tokens via `?token=<jwt>` in GET endpoints (e.g. SSE streams).
- **Bad Practice Example:**
  ```python
  # BAD: Accepting JWT from query string
  if not token:
      token = request.query_params.get("token")
  ```
- **Consequence:** URLs with query parameters are stored in plaintext in web server access logs, reverse proxy logs (Caddy), browser history, Cloudflare logs, and Sentry breadcrumbs.
- **Good Practice:**
  - Pass tokens via `Authorization: Bearer <token>` headers. Where the client genuinely cannot set one — `EventSource` is the only real case — mint a ticket instead: `cache.mint_sse_ticket` / `redeem_sse_ticket`, 30-second TTL, redeemed with `GETDEL` so it is worth exactly one connection. `POST /chat/notifications/ticket` is a normal header-authenticated request; only the ticket goes in the URL.
  - Redeem with a single atomic operation. A `GET` followed by a `DELETE` lets two connections racing on a leaked ticket both win.

---

## 2. AI Agent & LLM Security Anti-Patterns

### Anti-Pattern 2.1: Trusting Agent-Emitted External URLs as Verified Payment Links
- **Flaw:** Matching any markdown URL (`/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/`) and rendering it as an official "Secured by Stripe" checkout component.
- **Bad Practice Example:**
  ```typescript
  // BAD: Matches any external URL and renders PayCard with "Secured by Stripe" badge
  export const PAY_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/
  ```
- **Consequence:** Through prompt injection or hallucination, an agent can output `[Pay RM100 Now](https://malicious-phishing.com/pay)`. The frontend UI wraps it in an emerald card with the Stripe logo and lock icon, creating a high-trust phishing link.
- **Good Practice:**
  - Strictly enforce an allowlist on payment URL hostnames before rendering payment CTA cards:
  ```typescript
  // GOOD: Only permit canonical Stripe checkout domains
  export function isTrustedPaymentUrl(url: string): boolean {
    try {
      const parsed = new URL(url)
      return (
        parsed.protocol === 'https:' &&
        (parsed.hostname === 'buy.stripe.com' || parsed.hostname === 'checkout.stripe.com')
      )
    } catch {
      return false
    }
  }
  ```

---

### Anti-Pattern 2.2: Relying on System Prompts Alone for Business Logic Enforcement
- **Flaw:** Believing instructions like `"NEVER reveal min_price"` or `"Do not accept below RM50"` in `agent/config.py` are sufficient protection.
- **Consequence:** LLMs are non-deterministic and susceptible to prompt injection, jailbreaks, and indirect injection.
- **Good Practice:**
  - All critical business invariants (minimum floor prices, ownership scoping, payment statuses) **MUST be hard-coded into deterministic tool code** (Python functions) rather than delegated to the model prompt.

---

## 3. Network & Middleware Anti-Patterns

### Anti-Pattern 3.1: Trusting the Content-Length Header as the Size Limit
- **Flaw:** Only inspecting the `Content-Length` header in defense middleware to guard against payload bombs.
- **Bad Practice Example:**
  ```python
  # BAD: Bypassed when Transfer-Encoding: chunked is sent
  content_length_header = request.headers.get("content-length")
  if content_length_header:
      if int(content_length_header) > limit:
          return JSONResponse(status_code=413, ...)
  ```
- **Consequence:** Two requests walk straight past a header check: one that omits the header (`Transfer-Encoding: chunked`) and one that simply lies in it. Either way the endpoint's own `await request.body()` buffers whatever arrives. On the 1.2 GB Lightsail box that is an OOM, not a slow request.
- **Good Practice:**
  - Keep the header check — it refuses an honest oversized request before a byte is read — and **also count what actually arrives**. `core/defense_middleware.RequestDefenseMiddleware` wraps the ASGI `receive` channel, sums `http.request` body lengths, and returns `{"type": "http.disconnect"}` past the ceiling; Starlette turns that into `ClientDisconnect`, which the middleware catches and answers 413.
  - This is why that middleware is raw ASGI rather than `BaseHTTPMiddleware`: the latter only hands you a finished `Request`, and by the time you can measure the bytes they have already been buffered.
  - Do not "fix" it by feeding the app a truncated body with `more_body: False` — a handler would then accept a partial payload as a complete one.

---

### Anti-Pattern 3.2: Silent Fallbacks to Service-Role Privileges
- **Flaw:** Falling back from `USER_SUPABASE_KEY` to `ADMIN_SUPABASE_KEY` when the user key is missing.
- **Consequence:** Client-facing data queries silently bypass Row Level Security (RLS) and grant access to hidden/confidential columns or rows.
- **Good Practice:**
  - Fail closed with `_MissingSupabaseClient` or raise a configuration exception immediately. Never substitute service-role credentials for anon/authenticated roles.

---

## 4. Checklist for Future Agents

Before submitting PRs or deploying changes, verify:
- [ ] Are all mutating admin endpoints protected by `verify_admin` AND `verify_csrf_token`?
- [ ] Does every database update/delete query enforce strict `user_id` / ownership scoping?
- [ ] Are sensitive identity operations (email change, account delete) protected by password re-authentication?
- [ ] Are external URLs emitted by the AI validated against domain allowlists before being rendered with trust badges?
- [ ] Are auth tokens kept out of URL query parameters?
- [ ] Does request body size validation account for chunked transfers?
- [ ] Is the brute-force limit on credential checks keyed on the **account**, not the caller's IP?
- [ ] Does re-authentication use a per-request Supabase client rather than the shared singleton?

---

## 5. Where the enforcement actually lives

Grep these before re-deriving any of the above:

| Concern | Enforcement point |
|---|---|
| Admin CSRF | `routes/admin/__init__.py` — the `protected` router. Mount there; don't hand-roll the dependency. |
| Ownership scoping in agent tools | `agent/context.get_user_id()`, then fail closed. See `agent/tools/orders.check_user_orders` for the shape. |
| Account re-authentication | `routes/user._reauthenticate` |
| Per-request Supabase client | `connector.new_user_client` |
| Payment-link trust | `frontend/app/utils/chatBlocks.isTrustedPaymentUrl` |
| Request body ceiling | `core/defense_middleware.RequestDefenseMiddleware` |
| SSE authorisation | `cache.mint_sse_ticket` / `cache.redeem_sse_ticket` |
| Per-account throttling | `cache.check_rate_limit`; per-IP ceilings in `limiter.py` |

Specs: SPEC-044, SPEC-051, SPEC-056. ADRs: 0015, 0018.
