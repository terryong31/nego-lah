# API Reference & Specification

Nego-Lah provides a RESTful and event-driven API built with **FastAPI**, serving both the Nuxt 4 Single Page Application and the administrative console.

The complete machine-readable OpenAPI 3.1 specification is available in this directory:
📄 **[`openapi.json`](./openapi.json)** (also accessible at root [`api/openapi.json`](../../api/openapi.json))

---

## 1. Environments & Base URLs

| Environment | Base URL | OpenAPI Interactive Docs |
| :--- | :--- | :--- |
| **Production** | `https://api.negolah.my` | *Disabled (`docs_url=None`, RFC 9116 security posture)* |
| **Local Development** | `http://127.0.0.1:8000` | `http://127.0.0.1:8000/docs` (Swagger UI) <br> `http://127.0.0.1:8000/redoc` (ReDoc) |

---

## 2. Authentication & Security

Nego-Lah enforces layered authentication depending on the resource domain:

### Buyer Authentication (Supabase JWT)
- **Header:** `Authorization: Bearer <SUPABASE_ACCESS_TOKEN>`
- **Scope:** Used for user profile operations (`/users/*`), order history, and personal conversation access.
- **Provider:** Supabase Auth client-side SDK (`@nuxtjs/supabase`).

### Admin Console Authentication (2FA Cookie + CSRF)
- **Session Mechanism:** Two-factor authentication (Password + Email OTP).
- **Cookie:** `admin_sid` (`httpOnly`, `Secure` in prod, `SameSite=Strict`).
- **CSRF Token:** All mutating state changes (`POST`, `PUT`, `PATCH`, `DELETE`) on admin endpoints strictly require:
  - **Header:** `X-CSRF-Token: <token>`
- Mutating endpoints without CSRF verification fail closed immediately ([ANTI_PATTERNS.md](../security/ANTI_PATTERNS.md)).

### Bot Protection (Cloudflare Turnstile)
- High-risk operations (e.g., checkout creation, negotiation turn initiation, auth routes) enforce Turnstile token verification:
  - **Header:** `X-Turnstile-Token: <TOKEN>` or `cf-turnstile-response: <TOKEN>`

---

## 3. Core Resource Endpoints

### 3.1 Catalog (`/items`)
- `GET /items/` - List public active items (filtered by `status=available`, `deleted_at is null`).
- `GET /items/{item_id}` - Retrieve item public details (private floor `min_price` is withheld by column-level PostgreSQL grants).
- `GET /items/{item_id}/cache` - Lightweight cached item metadata for quick client cards.

### 3.2 AI Negotiation Engine (`/chat`)
- `POST /chat/{item_id}` - Send a buyer negotiation offer or inquiry. Triggers the LangGraph agent supervisor and specialized sub-agents.
- `GET /chat/{item_id}/stream` - Real-time Server-Sent Events (SSE) streaming of agent reasoning, typing events, and token responses.
- `GET /chat/{item_id}/history` - Retrieve append-only conversation transcript.
- `POST /chat/{item_id}/takeover` - Request human takeover (HITL).

### 3.3 Payments & Checkout (`/payment`)
- `POST /payment/checkout` - Create a Stripe checkout session with active negotiated pricing (optimistic claim at payment).
- `GET /payment/success` - Verify checkout completion and update order status to `confirmed`.
- `POST /payment/shipping` - Submit recipient delivery details (address, phone, recipient name).

### 3.4 Identity & Profile (`/users`)
- `GET /users/me` - Fetch authenticated user profile and notification counters.
- `PATCH /users/profile` - Update display name and durable avatar URL.
- `GET /users/orders` - Fetch authenticated user order history with shipment tracking.

### 3.5 Admin Operations (`/admin/*`)
- `GET /admin/dashboard` - Platform health, metrics, and revenue statistics.
- `GET /admin/chats` - Central HITL inbox displaying live negotiation states, read watermarks, and takeover switches.
- `POST /admin/chats/{user_id}/message` - Inject human seller message directly into a live negotiation.
- `POST /admin/orders/{order_id}/shipment` - Record carrier, tracking number, and tracking URL for fulfilled orders.
- `POST /admin/orders/{order_id}/refund` - Execute full or partial refund via Stripe.

### 3.6 Webhooks (`/webhooks`)
- `POST /webhooks/stripe` - Idempotent Stripe webhook receiver with signature validation (`Stripe-Signature`).
- `POST /webhooks/resend` - Email delivery tracking and bounce management.

---

## 4. Consuming the OpenAPI Specification

### Generating Client SDKs
You can generate TypeScript, Python, or Go API clients using OpenAPI Generator:
```bash
npx @openapitools/openapi-generator-cli generate \
  -i docs/api/openapi.json \
  -g typescript-fetch \
  -o frontend/app/api-client
```

### Viewing in Swagger UI Locally
```bash
# Run local dev backend
mise run dev:backend

# Open in browser:
open http://127.0.0.1:8000/docs
```
