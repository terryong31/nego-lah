# Getting started: your first negotiation

In this tutorial you run Nego-Lah on your machine, list an item as the seller, and haggle for it as
a buyer. It takes about 30 minutes. By the end you will have seen every major part of the system
work once: the SPA, the API, the session cookie, the agent and the price floor.

You will need a Supabase project (the team's staging project, through Infisical, is easiest), a
Gemini API key and an email inbox you can read.

## Prerequisites

- [mise](https://mise.jdx.dev/) (installs `uv`, `bun`, `infisical`, `lefthook`)
- Redis (`brew install redis`) — or point `REDIS_URL` at any Redis
- Docker, optional, for Mailpit
- A Supabase project, a Stripe test account and a Gemini API key, if you are not using the
  team's Infisical project

## 1. Install

```bash
mise install
(cd frontend && bun install)
(cd backend && uv sync)
mise run hooks:install
```

## 2. Provide secrets

**With Infisical** (team members): `infisical login` once. The `dev:*` tasks inject the `dev`
environment for you.

**Without Infisical:** copy the template and fill it in. Every variable is commented.

```bash
cp backend/.env.example backend/.env
```

The frontend needs no secrets in development: it defaults to `http://localhost:8000` and
disables Turnstile.

## 3. Run

```bash
mise run dev          # Redis + Mailpit + FastAPI :8000 + Nuxt :3000
```

Without Infisical, start the two apps yourself:

```bash
mise run dev:redis
mise run dev:mailpit
(cd backend && uv run uvicorn main:app --reload --port 8000)
(cd frontend && bun dev)
```

| URL | What |
|-----|------|
| <http://localhost:3000> | The SPA |
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8025> | Mailpit — every email the app sends in development |

## 4. Check the stack is up

```bash
curl -s localhost:8000/ready     # {"status": "ready", ...} once Redis is reachable
mise run test                    # backend + frontend suites
```

## 5. Create your account and make it a seller

1. Open <http://localhost:3000/register> and sign up with an email address you can read. Turnstile
   is off in development.
2. Supabase sends the confirmation email (this one does not go to Mailpit). Click the link; the
   API redeems it and sets your `nl_sid` session cookie.
3. Grant yourself the admin role:

   ```bash
   cd backend
   uv run python -m scripts.promote_admin grant you@example.com
   ```

## 6. List an item

1. Open <http://localhost:3000/_console/login> and sign in with your password and the one-time
   code that is emailed to you.
2. In **Items**, choose **Add Item**. Upload a photo; the vision model drafts the name,
   description and condition in English, Malay and Chinese.
3. Set a listing price of RM100 and a **Floor Price** of RM80, then save.

The floor is the lowest price the agent may accept. Postgres refuses to return it to anyone but
the backend, and it is never placed in a prompt ([ADR-0009](../adr/0009-confidential-columns-enforced-in-postgres.md)).

## 7. Haggle as the buyer

1. Open the storefront at <http://localhost:3000>, open your item and choose **Negotiate Price**.
2. Offer RM50. The agent calls `evaluate_offer`, which compares the offer with the floor on the
   server and returns a counter; the agent only phrases it.
3. Offer RM70, then RM85. Each counter lands on an RM5 step and never rises again
   ([SPEC-084](../specs/SPEC-084-server-enforced-negotiation-ratchet.md)).
4. Accept. The agent creates a Stripe payment link at the agreed price. In test mode, pay with
   card `4242 4242 4242 4242`. Stripe returns you to `/checkout/success`, which asks the API to
   confirm the payment with Stripe, and the item is marked sold. In production the signed
   webhook does this too; locally Stripe cannot reach your machine unless you run
   `stripe listen --forward-to localhost:8000/payment/webhook/stripe`.
5. Back in the console's **Chats**, the conversation is there. Switch the AI off and reply as the
   seller: the buyer's chat receives your message over SSE.

## What you have seen

- The SPA never held a token: every call used the session cookie and a CSRF header.
- The model never saw the floor: a tool enforced it.
- The sale was confirmed with Stripe by the server, not on the browser's word.

Next, read [Architecture](../architecture/README.md) for how these pieces fit, or
[Agent architecture](../architecture/agent.md) for what happened inside each turn.

## Troubleshooting

- **`Infisical login expired`** — run `infisical login` and retry.
- **`/ready` returns 503** — Redis is not reachable at `REDIS_URL`; `redis-cli ping` should answer
  `PONG`.
- **No emails in Mailpit** — Docker was not running when `dev:mailpit` started; start Docker and
  rerun it.
- **The agent always answers from Gemini** — expected unless `LOCAL_LLM_BASE_URL` points at a
  running OpenAI-compatible server; see [agent architecture](../architecture/agent.md#1-choosing-a-model-llm_factorypy).
