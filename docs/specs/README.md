# Specs (LeanSpec)

A spec is the contract for one change: the problem, the acceptance criteria, the design and the
tests that prove it. No non-trivial change starts without one (see [`AGENTS.md`](../../AGENTS.md)).

## Rules

- **Under 2,000 tokens.** A spec is read by people reviewing a PR and by agents implementing it;
  both do better with less. Put lasting rationale in an [ADR](../adr/README.md) and lasting
  description in the [living docs](../README.md#living-docs).
- **Start from [`TEMPLATE.md`](TEMPLATE.md).** Frontmatter `id:` must match the filename number,
  and numbers are never reused (`backend/tests/test_spec_registry.py` enforces both).
- **Status** is one of:

  | Status | Meaning |
  |--------|---------|
  | `draft` | Written, not started. |
  | `in-progress` | Being implemented; some acceptance criteria are open. |
  | `complete` | Every acceptance criterion is ticked **and verified against the code**, or explicitly marked *Dropped*, *Deferred* or *Superseded* with the reason. No `- [ ]` remains. |
  | `abandoned` | Not done. Say why in the spec. |
  | `superseded` | Replaced by a later spec; add `superseded_by: SPEC-NNN`. |

- **Specs are records.** Once `complete`, a spec describes what was built at the time. Do not
  edit it to track later changes — write a new spec that references it.

## Workflow

1. Draft the spec (`draft`): context, acceptance criteria, contracts, TDD scenarios, files.
2. Write the failing tests (`in-progress`).
3. Implement until they pass; tick each criterion as it is verified.
4. Set `complete`, then run `mise run docs:index`.

## Index

<!-- vale off -->
<!-- BEGIN GENERATED: do not edit by hand; run `mise run docs:index` -->
| Spec | Title | Status |
|------|-------|--------|
| [SPEC-000](SPEC-000-system-architecture.md) | Nego-Lah System Architecture & AI Negotiation Engine | complete |
| [SPEC-001](SPEC-001-dynamic-llm-failover.md) | Dynamic Local LLM Healthcheck, Tunnel & Gemini Failover | complete |
| [SPEC-002](SPEC-002-backend-modular-monolith.md) | Backend Modular Monolith Architecture & Domain Isolation | complete |
| [SPEC-003](SPEC-003-nuxt-spa-turnstile.md) | Nuxt SPA Migration to Cloudflare Pages & Universal Turnstile | complete |
| [SPEC-004](SPEC-004-connection-pool-and-ops.md) | Database Connection Pool, Infisical Multi-Folder Secrets, API Domain & Google Tag Manager | complete |
| [SPEC-005](SPEC-005-internationalization-and-human-readable-validation.md) | Full-Stack Trilingual i18n, Server Metadata Sync, and End-to-End Zod Validation | complete |
| [SPEC-006](SPEC-006-corporate-memphis-landing-hero.md) | Corporate Memphis Landing Page Hero Refactor | complete |
| [SPEC-007](SPEC-007-admin-otp-email-delivery-and-templates.md) | Admin OTP Email Delivery & Branded HTML Templates | complete |
| [SPEC-008](SPEC-008-trilingual-item-localization.md) | Trilingual Item Localization, Determinate Upload Progress, and Modal Polish | complete |
| [SPEC-009](SPEC-009-notifications-receipts-and-post-purchase-ux.md) | Real-Time SSE Notifications, Purchase Email Receipts & Post-Purchase UX | complete |
| [SPEC-010](SPEC-010-spa-loading-favicon-seo-branding.md) | SPA Loading Template, Favicon, SEO Meta, and Top Nav Logo | complete |
| [SPEC-011](SPEC-011-auth-routing-and-logout-redirection.md) | Auth Routing and Context-Aware Logout Redirection | complete |
| [SPEC-012](SPEC-012-admin-item-image-editing.md) | Admin Item Image Editing | complete |
| [SPEC-013](SPEC-013-chat-brand-work-indicator.md) | Branded Chat Work-Process Indicator | complete |
| [SPEC-014](SPEC-014-user-menu-dropdown-scroll-stability.md) | User Menu Dropdown Scroll Stability | complete |
| [SPEC-015](SPEC-015-sentry-telemetry-and-mobile-chat-spacing.md) | Industry-Standard Sentry Telemetry and Mobile Chat Layout Spacing | complete |
| [SPEC-016](SPEC-016-negotiated-price-and-checkout-handoff.md) | Negotiated Price, Checkout Hand-off and Outcome UX, and Stripe SDK v15 Compatibility | complete |
| [SPEC-017](SPEC-017-chat-notification-fanout-and-handover-indicator.md) | Chat Notification Fan-out, Self-Notification, and Hand-over Indicator | complete |
| [SPEC-018](SPEC-018-multi-worker-notification-fanout.md) | Multi-Worker Notification Fan-out and SSE Concurrency Hardening | complete |
| [SPEC-019](SPEC-019-realtime-chat-hitl-mobile-console-notifications.md) | Real-Time Chat, Human-in-the-Loop, Mobile Console, and Notification Gold Standards | complete |
| [SPEC-020](SPEC-020-dual-llm-hybrid-cloud-local-architecture.md) | Dual LLM Hybrid Cloud + Local Edge Architecture & Concurrency Load Balancer | complete |
| [SPEC-021](SPEC-021-modular-email-templates.md) | Modular Email Template Architecture with Jinja2 | complete |
| [SPEC-022](SPEC-022-env-conditional-sentry-and-turnstile.md) | Environment-Conditional Sentry Telemetry and Cloudflare Turnstile Verification | complete |
| [SPEC-023](SPEC-023-non-blocking-request-path.md) | Non-Blocking Request Path — Auth Dependency, Storefront and Stripe Webhook | complete |
| [SPEC-024](SPEC-024-build-ci-i18n-security-hardening.md) | Build Cache Optimization, Gold-Standard CI/CD, Full i18n Coverage, and Security Defense | complete |
| [SPEC-025](SPEC-025-motion-vue-negotiation-demo.md) | Motion for Vue Negotiation Demo Upgrade | abandoned |
| [SPEC-026](SPEC-026-product-video-showcase.md) | Product Walkthrough Video Showcase | complete |
| [SPEC-027](SPEC-027-chat-bubble-segmentation.md) | Authorship-Aware Chat Bubble Segmentation | complete |
| [SPEC-028](SPEC-028-storage-cdn-assets.md) | Supabase Storage CDN Assets and FastStart Video Streaming | complete |
| [SPEC-029](SPEC-029-oauth-callback-and-durable-avatar.md) | OAuth callback UX and durable custom avatar | complete |
| [SPEC-030](SPEC-030-service-worker-media-bypass.md) | Service Worker Media Bypass and Native PWA Install Prompt | complete |
| [SPEC-031](SPEC-031-item-card-padding-and-sold-treatment.md) | Item card padding parity and sold-item treatment | complete |
| [SPEC-032](SPEC-032-oauth-callback-redirect-loop.md) | OAuth callback stranded on the confirming spinner | complete |
| [SPEC-033](SPEC-033-crawlable-legal-pages.md) | Crawlable legal pages for Google OAuth verification | complete |
| [SPEC-034](SPEC-034-oauth-login-success-toast.md) | Success toast on Google sign-in | complete |
| [SPEC-035](SPEC-035-distinct-brand-identity-and-oauth-compliance.md) | Distinct Brand Identity, Vector Overhaul, and Google OAuth Compliance | complete |
| [SPEC-036](SPEC-036-confidential-item-fields.md) | Confidential item fields never leave the server | complete |
| [SPEC-037](SPEC-037-lease-ownership-and-hygiene.md) | Lease ownership + backend hygiene pass | complete |
| [SPEC-038](SPEC-038-pwa-service-worker-cloudflare-headers.md) | Progressive Web App (PWA), Cloudflare Pages Headers, CSP, and CORS Security | complete |
| [SPEC-039](SPEC-039-email-notification-design-and-item-name-resolution.md) | Transactional Email Design Overhaul & Item Name Resolution | complete |
| [SPEC-040](SPEC-040-session-expiry-return-redirect.md) | Session-Expiry Return Redirect — Land Back on the Page You Were Kicked Off | complete |
| [SPEC-041](SPEC-041-realtime-discount-sse-and-item-cache.md) | Real-Time Discount SSE Signal and Item Cache | complete |
| [SPEC-042](SPEC-042-cors-headers-on-defense-middleware-rejections.md) | CORS Headers on Defense-Middleware Rejections | complete |
| [SPEC-043](SPEC-043-capacity-hardening-under-concurrent-load.md) | Capacity Hardening Under Concurrent Negotiation Load | complete |
| [SPEC-044](SPEC-044-pre-conference-security-remediation.md) | Pre-Conference Security Remediation | complete |
| [SPEC-045](SPEC-045-r2-media-cdn.md) | Cloudflare R2 Media CDN for the Demo Video | complete |
| [SPEC-046](SPEC-046-console-chat-operability.md) | Console Chat Operability — AI-Status Sync, Filter, Sort, Search | complete |
| [SPEC-047](SPEC-047-human-like-negotiation-and-negotiated-checkout.md) | Human-Like Negotiation Concessions & Negotiated-Price Checkout | complete |
| [SPEC-048](SPEC-048-purchase-receipt-delivery.md) | Purchase-Receipt Email Delivery — Diagnosis & Hardening | complete |
| [SPEC-049](SPEC-049-transactional-email-visual-redesign.md) | Transactional & Auth Email Visual Redesign ("Ledger" System) | complete |
| [SPEC-050](SPEC-050-cloudflare-security-hardening.md) | Cloudflare Security Posture Hardening (HSTS, RFC 9116 Security.txt, SPF & DMARC Posture) | complete |
| [SPEC-051](SPEC-051-security-vulnerability-remediation.md) | Security Vulnerability Remediation - CORS Origin Restriction and Agent Tool Authorization Hardening | complete |
| [SPEC-052](SPEC-052-buffered-unread-message-digest.md) | Buffered Unread-Message Digest Email | complete |
| [SPEC-053](SPEC-053-admin-conversation-read-state.md) | Durable Admin Conversation Read State (Mark as Read) | complete |
| [SPEC-054](SPEC-054-image-normalization-and-heif.md) | Server-Side Image Normalization - Auto-Compression and HEIF Ingest | complete |
| [SPEC-055](SPEC-055-cod-and-fcfs-policy.md) | Cash-on-Delivery Refusal and First-Come-First-Served Policy | complete |
| [SPEC-056](SPEC-056-pre-launch-security-remediation.md) | Pre-Launch Security Remediation - CSRF, Fail-Open IDOR, Account Takeover, Payment-Link Spoofing | complete |
| [SPEC-057](SPEC-057-postage-and-shipment-tracking.md) | Postage & Shipment Tracking - Admin Upload, Buyer Notification, Agent Awareness | complete |
| [SPEC-058](SPEC-058-notification-listener-reconnect.md) | Notification Listener Reconnect (Hot-Spin Fix) | complete |
| [SPEC-059](SPEC-059-agent-cost-reduction-and-evaluation.md) | Agent Cost Reduction - Item Knowledge Card over Per-Turn Vision, and a Harness to Prove It | complete |
| [SPEC-060](SPEC-060-detached-chat-turn.md) | Agent Turn Survives the Buyer Closing the Tab | complete |
| [SPEC-061](SPEC-061-buyer-unread-watermark.md) | Buyer Unread State Survives a Reload | complete |
| [SPEC-062](SPEC-062-console-conversation-list-layout.md) | Console Conversation List Layout | complete |
| [SPEC-063](SPEC-063-conversation-row-actions.md) | Conversation Row Actions Menu (Archive / Read / Info) | complete |
| [SPEC-064](SPEC-064-order-lifecycle-actions.md) | Order Row Actions and the Shipment Modal | complete |
| [SPEC-065](SPEC-065-admin-table-filtering.md) | Global Filter on the Console Tables | complete |
| [SPEC-066](SPEC-066-utc-message-timestamps.md) | Read Watermarks Beat A Server That Isn't On UTC | complete |
| [SPEC-067](SPEC-067-notification-stream-recovery.md) | The Notification Stream Has To Come Back On Its Own | complete |
| [SPEC-068](SPEC-068-broker-membership-race.md) | A Live Stream Attached To A Channel Nobody Publishes To | complete |
| [SPEC-069](SPEC-069-agentic-marketplace-landing-and-onboarding.md) | The Front Page Sells A Shop, Not The Machine Behind It | complete |
| [SPEC-070](SPEC-070-mid-turn-broadcast-duplication.md) | A Broadcast That Lands Mid-Turn Duplicates The Whole Reply | complete |
| [SPEC-071](SPEC-071-marketplace-ghosting-hook-hero.md) | Landing Hero Repositioning — Facebook Marketplace Ghosting Hook | complete |
| [SPEC-072](SPEC-072-mobile-header-avatar-only.md) | Mobile Header Avatar-Only User Dropdown | complete |
| [SPEC-073](SPEC-073-pipeline-recording-empty-state.md) | Pipeline Recording Coming Soon UEmpty Component | complete |
| [SPEC-074](SPEC-074-mailpit-local-dev-email.md) | Mailpit Local Dev Email + Dev Resend Retirement Plan | complete |
| [SPEC-075](SPEC-075-three-step-pipeline-walkthrough.md) | Three-Step Pipeline Walkthrough (Upload → Nego → Delivery) | complete |
| [SPEC-076](SPEC-076-clear-user-chat-script.md) | Clear User Chat Ops Script | complete |
| [SPEC-077](SPEC-077-edge-proxy-pre-auth-rate-limiting-local-jwt.md) | Edge Proxy Lockdown, Pre-Routing ASGI Rate Limiting, and Local Cryptographic JWT Verification | complete |
| [SPEC-078](SPEC-078-post-purchase-shipping-flow-fixes.md) | Post-Purchase Shipping Flow Fixes | complete |
| [SPEC-079](SPEC-079-unified-single-agent-architecture.md) | Unified Single-Agent Architecture with Direct Tool Calling | complete |
| [SPEC-080](SPEC-080-agent-automatic-user-language-adaptation.md) | Agent Automatic User Language Adaptation | complete |
| [SPEC-081](SPEC-081-provider-specific-agent-prompts.md) | Provider-Specific Agent System Prompts | complete |
| [SPEC-082](SPEC-082-item-store-identity-scoping.md) | Item Store Identity Scoping | complete |
| [SPEC-083](SPEC-083-eval-harness-provider-targeting.md) | Eval Harness Provider Targeting | complete |
| [SPEC-084](SPEC-084-server-enforced-negotiation-ratchet.md) | Server-Enforced Negotiation Ratchet | complete |
| [SPEC-085](SPEC-085-supabase-user-id-resolution.md) | Supabase User ID Resolution | complete |
| [SPEC-086](SPEC-086-cod-handoff-carries-the-fcfs-caveat.md) | COD Handoff Carries the FCFS Caveat | complete |
| [SPEC-087](SPEC-087-replay-tool-calls-in-agent-history.md) | Replay Tool Calls in Agent History | complete |
| [SPEC-088](SPEC-088-payment-links-must-be-server-issued.md) | Payment Links Must Be Server-Issued | complete |
| [SPEC-089](SPEC-089-checkout-cannot-undercut-the-standing-price.md) | Checkout Cannot Undercut the Standing Price | complete |
| [SPEC-090](SPEC-090-eval-harness-multi-turn-fidelity.md) | Eval Harness Multi-Turn Fidelity | complete |
| [SPEC-091](SPEC-091-local-decide-then-speak-agent.md) | Local Qwen Decide-Then-Speak Agent | complete |
| [SPEC-092](SPEC-092-modular-monolith-realization.md) | Backend Modular Monolith Realization — Code Relocation & Domain Boundaries | complete |
| [SPEC-093](SPEC-093-server-side-session-httponly-cookies.md) | Server-Side Sessions — httpOnly Cookies for the Buyer App | in-progress |
| [SPEC-094](SPEC-094-realtime-over-the-notification-broker.md) | Realtime Over the Notification Broker, Not a Public Supabase Channel | in-progress |
| [SPEC-095](SPEC-095-boundary-enforcement-covers-the-whole-backend.md) | Boundary Enforcement Covers the Whole Backend | complete |
| [SPEC-096](SPEC-096-migrations-run-in-cicd.md) | Supabase Migrations Run in CI/CD, Not From a Laptop | complete |
| [SPEC-097](SPEC-097-the-domain-graph-is-acyclic.md) | An Actual Modular Monolith — Acyclic Domains, One Composition Root | complete |
| [SPEC-098](SPEC-098-retire-the-conversations-table.md) | Retire the `conversations` Table — Reversibly | complete |
| [SPEC-099](SPEC-099-the-walkthrough-video-starts-before-you-need-it.md) | The Walkthrough Video Starts Loading Before You Need It | complete |
| [SPEC-100](SPEC-100-one-intro-video.md) | One Motion-Graphics Intro Video Replaces the Three-Step Walkthrough | complete |
| [SPEC-101](SPEC-101-non-functional-audit-remediation.md) | Non-Functional Audit Remediation (2026-10-06) | complete |
| [SPEC-102](SPEC-102-docs-are-checked-like-code.md) | Docs Are Checked Like Code | complete |
| [SPEC-103](SPEC-103-dependabot-dependency-updates.md) | Dependabot Owns Dependency Updates | complete |
| [SPEC-104](SPEC-104-security-audit-remediation.md) | Security Audit Remediation (2026-10-07) | in-progress |
<!-- END GENERATED -->
<!-- vale on -->
