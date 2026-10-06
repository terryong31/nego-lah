# Nego-Lah Documentation Hub

Welcome to the **Nego-Lah** engineering documentation hub. This documentation is organized according to the industry-standard **Diátaxis documentation framework**, categorizing content by developer intent: **Explanation**, **Reference**, **How-To Guides**, and **Tutorials**.

---

## 1. Documentation Map (Diátaxis)

```
                       PRACTICAL
                           │
       TUTORIALS           │         HOW-TO GUIDES
   (Learning-oriented)     │      (Problem-oriented)
                           │
  • Quickstart in README   │   • Admin Promotion
  • Frontend Setup         │   • Email Diagnostics
  • Supabase Connect       │   • CI/CD Deployment
                           │
───────────────────────────┼───────────────────────────
                           │
       EXPLANATION         │          REFERENCE
   (Understanding-oriented)│     (Information-oriented)
                           │
  • Architecture (SPEC-000)│   • OpenAPI 3.1 Specification
  • Monorepo Structure     │   • Database Models & RLS
  • ADRs (ADR-0001..0031)  │   • Background Worker Loops
  • Security Standards     │   • LeanSpecs (SPEC-001..101)
                           │
                      THEORETICAL
```

---

## 2. Directory Index

### 📘 [Architecture](./architecture/README.md) *(Explanation)*
- [System Architecture Specification (SPEC-000)](./architecture/SPEC-000-system-architecture.md) — Hybrid edge/cloud dual-LLM load balancer, LangGraph negotiation engine, and edge SPA design.
- [Architecture Decision Records (ADRs)](./adr/README.md) — Chronological log of major architectural decisions (ADR-0001 through ADR-0031).

### 📄 [API Reference & OpenAPI](./api/README.md) *(Reference)*
- Complete RESTful and SSE endpoint documentation.
- Machine-readable [OpenAPI 3.1 Specification](./api/openapi.json).
- Auth scopes (Supabase JWT vs. Admin 2FA Cookie), CSRF tokens, and Turnstile headers.

### 🗄️ [Data Architecture & Schemas](./data/README.md) *(Reference)*
- Entity Relationship diagrams and table models (`items`, `orders`, `messages`, `transactions`).
- Column-level confidentiality for floor prices (`min_price`).
- Row-Level Security (RLS), soft-deletes, and sequential SQL migrations list.

### 🏗️ [Monorepo & Tooling](./repo/README.md) *(Explanation & Reference)*
- Complete repository tree, directory responsibilities, and domain boundary isolation rules.
- Pinned tooling contracts (`mise`, `uv`, `bun`, `infisical`, `lefthook`).

### ⚙️ [CI/CD & Deployment](./ci-cd/README.md) *(How-To & Reference)*
- Path-filtered GitHub Actions deployment pipeline.
- Cloudflare Pages edge static asset generation and AWS Lightsail container deployment.
- Code coverage gates (88%) and automated security audits.

### 🔄 [Background Workers](./workers/README.md) *(Reference)*
- In-process lifespan worker loops on AWS Lightsail.
- `_payment_cleanup_loop` (Stripe link deactivation & inventory restoration).
- `_unread_digest_loop` (5-minute buffered notification digest queue).

### 🔀 [Core System Flows](./flows/README.md) *(Explanation)*
- Sequence diagrams for AI Bargaining & SSE streaming, checkout claims, and HITL handover.

### 🛡️ [Security Standards](./security/ANTI_PATTERNS.md) *(Explanation & Guide)*
- Real vulnerabilities and anti-patterns catalogued during security audits.
- CSRF protection, fail-closed query scoping, and PII redaction rules.

### 🔍 [Audits](./audits/2026-10-06-non-functional-audit.md) *(Reference)*
- 2026-10-06 non-functional audit: security, privacy, reliability, performance, scalability, cost, observability, DR, supply chain, accessibility and SEO, with a prioritised remediation roadmap.

### 📋 [LeanSpecs](./specs/README.md) *(Reference & Specification)*
- All 100+ Spec-Driven Development (SDD) feature contracts (<2k tokens each) driving test-driven implementation.
