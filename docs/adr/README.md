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
| [0014](0014-cloudflare-security-posture-hardening.md) | Cloudflare Security Posture Hardening (HSTS, RFC 9116, SPF/DMARC) | Accepted |
| [0015](0015-cors-origin-and-agent-tool-authorization-hardening.md) | CORS Origin and Agent Tool Authorization Hardening | Accepted |
| [0016](0016-buffered-notification-digests.md) | Buffered Notification Digests over Per-Message Email | Accepted |
| [0017](0017-server-side-image-normalization.md) | Server-Side Image Normalization (HEIF Ingest and Auto-Compression) | Accepted |
| [0018](0018-pre-launch-security-remediation.md) | Pre-Launch Security Remediation — Trust Boundaries an Audit Found Open | Accepted |
| [0019](0019-seller-reported-shipment-tracking.md) | Seller-Reported Shipment Tracking | Accepted |
| [0020](0020-item-knowledge-card-over-per-turn-vision.md) | An Item Knowledge Card Instead of Re-Sending the Photos Every Turn | Accepted |
| [0021](0021-agent-turns-outlive-their-http-response.md) | Agent Turns Outlive the HTTP Response That Requested Them | Accepted |
| [0022](0022-a-message-from-the-future-is-history.md) | A Message From the Future Is History, Not News | Accepted |
| [0023](0023-the-design-system-already-had-a-tour.md) | The Design System Already Had a Tour, and Its Anchor Does Not Watch the DOM | Accepted |
| [0024](0024-what-a-tool-hands-back-and-when-the-buyer-sees-it.md) | What a Tool Hands Back, and When the Buyer Sees It | Accepted |
| [0025](0025-edge-proxy-pre-auth-rate-limiting-local-jwt.md) | Edge Proxy Lockdown, Pre-Routing ASGI Rate Limiting, and Local JWT Verification | Accepted |
| [0026](0026-unified-single-agent-architecture.md) | Unified Single-Agent Architecture with Direct Tool Calling | Accepted |
| [0027](0027-code-relocation-into-domain-packages.md) | Move the Code into the Domain Packages (Modular Monolith Realized) | Accepted |
| [0028](0028-buyer-sessions-move-behind-the-api.md) | Buyer Sessions Move Behind the API, Not Into an SSR Server | Accepted |
| [0029](0029-ci-owns-production-migrations.md) | CI Owns Production Migrations | Accepted |
| [0030](0030-the-domain-graph-is-acyclic.md) | The Domain Graph Is Acyclic (Layering, Bus, Composition Root) | Accepted |
| [0031](0031-videos-are-code.md) | Videos Are Code (Remotion, Rendered Out of Git) | Accepted |
