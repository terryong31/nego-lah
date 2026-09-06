# LeanSpec - Spec-Driven Development (SDD)

This directory houses all engineering specifications for **Nego-Lah** following the **LeanSpec** standard.

## Principles of LeanSpec

1. **Context Economy:** Keep specs concise (<2,000 tokens) so they easily fit into AI agent context windows without polluting reasoning tokens.
2. **Spec-Driven Development:** No code is written without a corresponding spec in `specs/SPEC-XXX-<feature>.md`.
3. **Traceability:** Every spec links directly to its acceptance criteria, automated tests, and implementation files.

---

## Spec Workflow

```
1. Draft Spec (status: draft)
   └── Define Context, Acceptance Criteria, API Contracts, Test Scenarios
2. Implement TDD Tests (status: in-progress)
   └── Write unit/integration tests that fail initially
3. Implement Feature Code
   └── Write minimal code until tests pass (Green)
4. Finalize & Verify (status: complete)
   └── Lint, test coverage check, update spec status to complete
```

---

## Current Specs

- [TEMPLATE.md](./TEMPLATE.md) - Standard LeanSpec template.
- [SPEC-001-dynamic-llm-failover.md](./SPEC-001-dynamic-llm-failover.md) - Dynamic availability probe & failover for local Qwen model.
- [SPEC-002-backend-modular-monolith.md](./SPEC-002-backend-modular-monolith.md) - Modular monolith architecture for AWS Lightsail.
- [SPEC-003-nuxt-spa-turnstile.md](./SPEC-003-nuxt-spa-turnstile.md) - Nuxt SPA on Cloudflare Pages with Universal Turnstile.
- [SPEC-004-connection-pool-and-ops.md](./SPEC-004-connection-pool-and-ops.md) - Direct PostgreSQL connection pool and secrets management.
- [SPEC-005-internationalization-and-human-readable-validation.md](./SPEC-005-internationalization-and-human-readable-validation.md) - Full-Stack i18n (EN/MS/ZH) and Human-Readable Validation Messages.
- [SPEC-013-chat-brand-work-indicator.md](./SPEC-013-chat-brand-work-indicator.md) - Branded chat work-process indicator: hopping brand mark and "Cooking…" label.
- [SPEC-016-negotiated-price-and-checkout-handoff.md](./SPEC-016-negotiated-price-and-checkout-handoff.md) - Negotiated price surfacing, checkout hand-off card, and Stripe SDK v15 object-access compatibility.
- [SPEC-017-chat-notification-fanout-and-handover-indicator.md](./SPEC-017-chat-notification-fanout-and-handover-indicator.md) - Duplicate/self notifications and the AI hand-over indicator in the buyer chat.
- [SPEC-020-dual-llm-hybrid-cloud-local-architecture.md](./SPEC-020-dual-llm-hybrid-cloud-local-architecture.md) - Dual LLM Hybrid Cloud + Local Edge Architecture & Concurrency Load Balancer.
- [SPEC-025-motion-vue-negotiation-demo.md](./SPEC-025-motion-vue-negotiation-demo.md) - Motion for Vue Negotiation Demo Upgrade.
- [SPEC-036-confidential-item-fields.md](./SPEC-036-confidential-item-fields.md) - Keep `min_price` and other seller-confidential columns off the public API and out of PostgREST's reach.
- [SPEC-037-lease-ownership-and-hygiene.md](./SPEC-037-lease-ownership-and-hygiene.md) - Token-owned local-LLM lease, cursored Redis scans, SQLSTATE error detection, coverage gate, module splits.

> This index is not exhaustive — `ls specs/` is the source of truth. Spec numbers
> are unique and match their frontmatter `id:`; `backend/tests/test_spec_registry.py`
> enforces both.
