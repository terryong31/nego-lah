# Architecture Decision Records

Short documents capturing significant architectural decisions: the context, the
options weighed, the choice made, and its consequences. One file per decision,
numbered sequentially. Supersede rather than rewrite — if a later decision
changes an earlier one, add a new ADR and mark the old one's status.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-payment-concurrency-optimistic-claim.md) | Optimistic claim-at-payment over pessimistic inventory locking | Accepted |
| [0002](0002-modular-monolith-over-grpc-microservices.md) | Modular Monolith over Distributed gRPC Microservices | Accepted |
| [0003](0003-dual-provider-multimodal-llm-failover.md) | Dual-Provider Multimodal LLM Factory with Dynamic Failover | Accepted |
| [0004](0004-nuxt-spa-cloudflare-pages-and-turnstile.md) | Nuxt SPA on Cloudflare Pages with Universal Turnstile Bot Protection | Accepted |
| [0005](0005-infisical-secrets-management-and-api-domain.md) | Multi-Folder Infisical Secrets, Dedicated API Domain, and Google Analytics | Accepted |
| [0006](0006-sentry-session-replay-and-distributed-tracing.md) | Sentry Session Replay and Distributed Tracing Architecture | Accepted |
| [0007](0007-hybrid-edge-cloud-llm-load-balancer.md) | Hybrid Edge-Cloud LLM Load Balancer with Atomic Concurrency Leases | Accepted |
| [0008](0008-build-time-content-injection-for-legal-pages.md) | Build-Time Content Injection for Crawler-Readable Legal Pages | Accepted |
| [0009](0009-confidential-columns-enforced-in-postgres.md) | Seller-Confidential Columns Enforced in Postgres, Not Just in the API | Accepted |
| [0010](0010-cloudflare-r2-media-cdn.md) | Cloudflare R2 for Large Static Media, Not Supabase Storage | Accepted |
| [0011](0011-human-like-negotiation-concessions.md) | Human-Like Negotiation Concessions | Accepted |
| [0012](0012-transactional-email-sender-and-alerting.md) | Transactional Email — Sender Mailbox and Failure Alerting | Accepted |
| [0013](0013-ledger-email-design-system.md) | One "Ledger" Design System for All Transactional and Auth Emails | Accepted |
