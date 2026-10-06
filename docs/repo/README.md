# Repository Guide

Where things live and which tools run them. Living document. Rules for changing code are in
[`AGENTS.md`](../../AGENTS.md); this page is the map.

## Layout

```text
nego-lah/
├── frontend/                 Nuxt 4 SPA (ssr: false) → Cloudflare Pages
│   ├── app/                  pages, components, composables, stores, middleware, plugins
│   ├── i18n/                 en / ms / zh message catalogues
│   ├── build/                build-time helpers (CSP source, legal-page injection)
│   ├── tests/                Vitest
│   └── wrangler.toml         Pages config
│
├── backend/                  FastAPI modular monolith → AWS Lightsail (Docker)
│   ├── main.py               app, middleware, routers, lifespan loops, bus wiring
│   ├── core/                 infrastructure: env, Redis, Supabase connector, CSRF, bus, email…
│   ├── domains/              identity · catalog · billing · negotiation (+ webhooks)
│   ├── console/              admin screens that compose several domains
│   ├── templates/emails/     Jinja "Ledger" email templates
│   ├── evals/                agent evaluation harness (mise run eval:agent)
│   ├── scripts/              operational scripts (admin, migrations, diagnostics, docs)
│   └── tests/                pytest, 88% coverage gate
│
├── supabase/
│   ├── migrations/           append-only SQL; applied to production by CI
│   └── templates/            Supabase Auth email templates
│
├── video/                    Remotion source for the homepage intro (ADR-0031)
├── docs/                     this documentation
├── scripts/                  host-level scripts (Lightsail firewall)
├── .github/workflows/        deploy.yml (CI/CD), uptime.yml, ops-revoke-sessions.yml
├── docker-compose.yml        production stack: Caddy + backend (Redis is managed Upstash)
├── Caddyfile                 TLS and reverse proxy
├── mise.toml                 tool versions and every task
└── lefthook.yml              git hooks
```

The backend's internal rules — layers, domain ranking, table ownership, the event bus — are
described in [Architecture](../architecture/README.md#backend-structure) and enforced by
`backend/tests/test_domain_boundaries.py`.

## Toolchain

[mise](https://mise.jdx.dev/) pins every tool and defines every task. `mise tasks` lists them.

| Tool | Used for |
|------|----------|
| `uv` | Python dependencies and the `backend/.venv` virtualenv |
| `bun` | Frontend and video dependencies and scripts |
| `infisical` | Injecting secrets into dev, CI and production processes |
| `lefthook` | Git hooks: lint on commit; backend tests and frontend typecheck on push |

## Everyday tasks

| Task | Command |
|------|---------|
| Run everything locally | `mise run dev` |
| Tests (backend + frontend) | `mise run test` |
| Lint / typecheck | `mise run lint`, `mise run typecheck` |
| Dependency audit | `mise run audit` |
| Validate migration files | `mise run db:validate` |
| Regenerate API spec / doc indexes | `mise run docs:openapi`, `mise run docs:index` |
| Evaluate the agent | `mise run eval:agent` |

Step-by-step guides are in [How-to](../how-to/README.md).
