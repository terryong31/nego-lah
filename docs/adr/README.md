# Architecture Decision Records

An ADR records one significant decision: the forces at the time, the options weighed, what was
chosen and what it costs. They follow [Michael Nygard's format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
with the metadata block from [`TEMPLATE.md`](TEMPLATE.md).

## Rules

- **Write one when** a choice is hard to reverse, constrains future work, or a reasonable engineer
  would ask "why did they do it this way?" — a new dependency, a layer boundary, a data-ownership
  rule, an infrastructure move. A feature that follows existing patterns needs a
  [spec](../specs/README.md), not an ADR.
- **ADRs are records, not living docs.** Never rewrite the body of an accepted ADR. When a later
  decision changes it, write a new ADR and set the old one's status to `Superseded by ADR-NNNN`
  (or add `- Superseded in part by:` when only part of it changed).
- **Number sequentially**, `NNNN-kebab-title.md`. The index below is generated from each file's
  metadata block; run `mise run docs:index` after adding one. `backend/tests/test_docs.py` fails
  when it is stale.

## Index

<!-- vale off -->
<!-- BEGIN GENERATED: do not edit by hand; run `mise run docs:index` -->
| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-payment-concurrency-optimistic-claim.md) | Optimistic claim-at-payment over pessimistic inventory locking | Accepted | 2026-06-30 |
| [0002](0002-modular-monolith-over-grpc-microservices.md) | Modular Monolith over Distributed gRPC Microservices | Accepted | 2026-09-04 |
| [0003](0003-dual-provider-multimodal-llm-failover.md) | Dual-Provider Multimodal LLM Factory with Dynamic Failover | Accepted | 2026-09-04 |
| [0004](0004-nuxt-spa-cloudflare-pages-and-turnstile.md) | Nuxt SPA on Cloudflare Pages with Universal Turnstile Bot Protection | Accepted | 2026-09-04 |
| [0005](0005-infisical-secrets-management-and-api-domain.md) | Multi-Folder Infisical Secrets, Dedicated API Domain, and Google Analytics | Accepted | 2026-09-04 |
| [0006](0006-sentry-session-replay-and-distributed-tracing.md) | Sentry Session Replay and Distributed Tracing Architecture | Accepted | 2026-09-06 |
| [0007](0007-hybrid-edge-cloud-llm-load-balancer.md) | Hybrid Edge-Cloud LLM Load Balancer with Atomic Concurrency Leases | Accepted | 2026-09-05 |
| [0008](0008-build-time-content-injection-for-legal-pages.md) | Build-Time Content Injection for Crawler-Readable Legal Pages | Accepted | 2026-09-06 |
| [0009](0009-confidential-columns-enforced-in-postgres.md) | Seller-Confidential Columns Enforced in Postgres, Not Just in the API | Accepted | 2026-09-06 |
| [0010](0010-cloudflare-r2-media-cdn.md) | Cloudflare R2 for Large Static Media, Not Supabase Storage | Accepted | 2026-09-08 |
| [0011](0011-human-like-negotiation-concessions.md) | Human-Like Negotiation Concessions | Accepted | 2026-09-09 |
| [0012](0012-transactional-email-sender-and-alerting.md) | Transactional Email — Sender Mailbox and Failure Alerting | Accepted | 2026-09-09 |
| [0013](0013-ledger-email-design-system.md) | One "Ledger" Design System for All Transactional and Auth Emails | Accepted | 2026-09-09 |
| [0014](0014-cloudflare-security-posture-hardening.md) | Cloudflare Security Posture Hardening (HSTS, RFC 9116, SPF/DMARC) | Accepted | 2026-09-09 |
| [0015](0015-cors-origin-and-agent-tool-authorization-hardening.md) | CORS Origin and Agent Tool Authorization Hardening | Accepted | 2026-09-09 |
| [0016](0016-buffered-notification-digests.md) | Buffered Notification Digests over Per-Message Email | Accepted | 2026-09-09 |
| [0017](0017-server-side-image-normalization.md) | Server-Side Image Normalization (HEIF Ingest and Auto-Compression) | Accepted | 2026-09-09 |
| [0018](0018-pre-launch-security-remediation.md) | Pre-Launch Security Remediation — Trust Boundaries an Audit Found Open | Accepted | 2026-09-10 |
| [0019](0019-seller-reported-shipment-tracking.md) | Seller-Reported Shipment Tracking | Accepted | 2026-09-10 |
| [0020](0020-item-knowledge-card-over-per-turn-vision.md) | An Item Knowledge Card Instead of Re-Sending the Photos Every Turn | Accepted | 2026-09-10 |
| [0021](0021-agent-turns-outlive-their-http-response.md) | Agent Turns Outlive the HTTP Response That Requested Them | Accepted | 2026-09-10 |
| [0022](0022-a-message-from-the-future-is-history.md) | A Message From the Future Is History, Not News | Accepted | 2026-09-10 |
| [0023](0023-the-design-system-already-had-a-tour.md) | The Design System Already Had a Tour, and Its Anchor Does Not Watch the DOM | Accepted | 2026-09-16 |
| [0024](0024-what-a-tool-hands-back-and-when-the-buyer-sees-it.md) | What a Tool Hands Back, and When the Buyer Sees It | Accepted | 2026-09-16 |
| [0025](0025-edge-proxy-pre-auth-rate-limiting-local-jwt.md) | Edge Proxy Lockdown, Pre-Routing ASGI Rate Limiting, and Local Cryptographic JWT Verification | Accepted | 2026-09-14 |
| [0026](0026-unified-single-agent-architecture.md) | Unified Single-Agent Architecture with Direct Tool Calling | Accepted | 2026-09-16 |
| [0027](0027-code-relocation-into-domain-packages.md) | Move the code into the domain packages | Accepted | 2026-09-17 |
| [0028](0028-buyer-sessions-move-behind-the-api.md) | Buyer Sessions Move Behind the API, Not Into an SSR Server | Accepted | 2026-09-18 |
| [0029](0029-ci-owns-production-migrations.md) | CI owns production migrations | Accepted | 2026-09-18 |
| [0030](0030-the-domain-graph-is-acyclic.md) | The domain graph is acyclic | Accepted | 2026-09-20 |
| [0031](0031-videos-are-code.md) | Videos Are Code | Accepted | 2026-10-07 |
| [0032](0032-origin-authenticated-by-zone-secret-header.md) | The origin authenticates our Cloudflare zone with a secret header | Accepted | 2026-10-07 |
<!-- END GENERATED -->
<!-- vale on -->
