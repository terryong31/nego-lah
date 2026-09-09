# 14. Cloudflare Security Posture Hardening (HSTS, RFC 9116, SPF/DMARC)

- Status: Accepted
- Date: 2026-09-09
- Deciders: Terry (owner), AI Agent
- Relates to: SPEC-050; builds on ADR 0004 (Cloudflare Pages), ADR 0005 (API domain), ADR 0012 (Transactional Email)

## Context

A comprehensive Cloudflare Security Center audit of `negolah.my` identified 16 security posture gaps across transport security, email authentication, bot management, and access controls:
1. HTTP requests to proxied subdomains (`llm.negolah.my`, `media.negolah.my`) did not 301-redirect to HTTPS because zone-level "Always Use HTTPS" was unconfigured.
2. No `Strict-Transport-Security` (HSTS) header was emitted for `negolah.my`, `www`, `llm`, or `media`.
3. Missing RFC 9116 vulnerability reporting standard (`/.well-known/security.txt`).
4. An inbound MX record points to AWS SES (`inbound-smtp.ap-northeast-1.amazonaws.com`), but no SPF TXT record was configured at the apex domain `@` (`negolah.my`), exposing the domain to email spoofing warnings.
5. The DMARC record `_dmarc.negolah.my` was present as `v=DMARC1; p=none;` but lacked an aggregate reporting mailbox (`rua=`), preventing delivery analysis and triggering Cloudflare Email Security alerts.
6. Cloudflare Bot Fight Mode and AI Labyrinth were not enabled on the zone.
7. The Cloudflare administrator account lacked multi-factor authentication (MFA/2FA).

## Decision

1. **Defense-in-Depth HSTS:**
   - Enforce HSTS at the static edge in `frontend/public/_headers` with `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` for Cloudflare Pages.
   - Enforce HSTS in `Caddyfile` for `api.negolah.my` in addition to FastAPI's `SecurityHeadersMiddleware`.
   - Enable HSTS with subdomains and preload in Cloudflare SSL/TLS Edge Certificates.

2. **RFC 9116 Security Vulnerability Disclosure:**
   - Provide `frontend/public/.well-known/security.txt` containing contact addresses, canonical URL, language preference, and policy links.
   - Add root repository `SECURITY.md` defining reporting channels and service level objectives.
   - Serve `/.well-known/security.txt` with `Content-Type: text/plain; charset=utf-8` and cache-control.

3. **Email Authentication Alignment:**
   - Configure apex TXT record `v=spf1 include:amazonses.com ~all` to authorize Resend's sending infrastructure (AWS SES ap-northeast-1) from which `receipts@negolah.my` is dispatched.
   - Update `_dmarc.negolah.my` to `v=DMARC1; p=none; rua=mailto:terryong30@gmail.com; aspf=r;` (or Cloudflare DMARC Management address).

4. **Zone & Account Hardening:**
   - Turn on "Always Use HTTPS" at Cloudflare zone level.
   - Turn on Bot Fight Mode and AI Labyrinth in Cloudflare Security dashboard.
   - Enforce MFA on the Cloudflare administrator account.

## Consequences

- **Positive:**
  - Prevents SSL stripping, protocol downgrade attacks, and MITM attacks via HSTS and automatic HTTPS redirects.
  - Fixes email deliverability and prevents email spoofing alerts by aligning apex SPF and DMARC reporting.
  - Complies with RFC 9116 and industry vulnerability disclosure standards.
  - Mitigates unauthorized bot scraping and AI crawler abuse via Cloudflare edge protections.
- **Operator Actions Required:**
  - DNS TXT records, zone-level SSL/TLS settings, and user 2FA cannot be managed by deployment OAuth tokens and must be confirmed in Cloudflare Dashboard.
