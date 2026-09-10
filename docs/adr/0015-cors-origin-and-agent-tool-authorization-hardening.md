# ADR 0015: CORS Origin and Agent Tool Authorization Hardening

## Status
Accepted

## Context
Following an audit of potential customer data exposure vectors inspired by recent Malaysian e-commerce/delivery data breaches, two critical authorization and origin boundaries were identified for hardening:

1. **Cloudflare Pages CORS Origin Scope**:
   In `backend/main.py`, `_ORIGIN_REGEX` permitted all subdomains under `pages.dev` (`r"^https://([a-zA-Z0-9_-]+\.)*pages\.dev$"`). When paired with `allow_credentials=True`, this opened cross-origin access to any third-party website hosted on Cloudflare Pages (`https://<attacker>.pages.dev`), allowing credentialed browser requests to read sensitive JSON responses (orders, chats, user profiles).
2. **AI Tool Order Authorization (IDOR)**:
   In `backend/agent/tools/payment.py`, `collect_shipping_info` accepted an `order_id` parameter and directly mutated recipient delivery details (name, phone, address) with only `.eq('id', order_id)`. The function did not verify that the order belonged to the requesting session (`buyer_id == user_id`), allowing potential cross-tenant shipping address hijacking.
3. **PII Logging**:
   Plaintext recipient phone numbers and physical addresses were logged into standard application logs, creating exposure risks in log aggregators and Sentry traces.

## Decision

1. **Eliminate Regex in Production & Restrict Previews to Project in Dev**:
   In `backend/main.py`, `_ORIGIN_REGEX` is set to `None` in production (`IS_PROD = True`). Production API requests strictly accept only the explicit canonical domains in `_PROD_ORIGINS` (`https://negolah.my`, `https://www.negolah.my`).
   In non-production environments (development/staging), `_ORIGIN_REGEX` is set to `r"^https://([a-zA-Z0-9_-]+\.)*nego-lah\.pages\.dev$"` to support preview branches. Arbitrary `*.pages.dev` domains are strictly rejected across all environments.

2. **Enforce Buyer ID Scoping in `collect_shipping_info`**:
   Retrieve the authenticated context user via `agent.context.get_user_id()`. When present, chain `.eq('buyer_id', user_id)` onto the database update query. If the order ID does not belong to the active user, the database update matches 0 rows and returns an error without mutating another customer's record.

3. **Mask Sensitive Customer PII in Tool Logs**:
   In `collect_shipping_info`, mask phone numbers (e.g., `012****89`) and addresses (truncate with ellipses) before writing to `logger.info`.

## Consequences

- **Security**: Completely closes the cross-origin authenticated read vulnerability on `pages.dev` and prevents order hijacking via the conversational agent.
- **Privacy & Compliance**: Eliminates plaintext PII in logs, adhering to Malaysian Personal Data Protection Act 2010 (PDPA) security standards.
- **Compatibility**: The frontend running on `https://negolah.my`, `https://nego-lah.pages.dev`, or branch preview URLs (e.g., `https://pr-12.nego-lah.pages.dev`) continues to operate normally without any client-side changes.
