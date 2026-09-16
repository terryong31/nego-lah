---
id: SPEC-050
title: Cloudflare Security Posture Hardening (HSTS, RFC 9116 Security.txt, SPF & DMARC Posture)
status: completed
priority: high
created: 2026-09-09
tags: [security, cloudflare, headers, dns, email, hsts]
assigned: agent
---

# Context & Objectives
A security audit from Cloudflare Security Center detected several configuration weaknesses across `negolah.my`, subdomains (`llm`, `media`), Cloudflare Pages (`nego-lah.pages.dev`), and administrative settings:
1. **Missing HSTS:** No `Strict-Transport-Security` header in HTTPS responses from Cloudflare Pages or proxied services.
2. **Missing Security.txt:** No RFC 9116 `/.well-known/security.txt` declaration for responsible vulnerability disclosure.
3. **Incomplete Email Auth:** The apex domain has an active AWS SES inbound MX record, but lacks a corresponding apex TXT SPF record (Resend only configured `send.negolah.my`), and the DMARC TXT record lacks an aggregate reporting URI (`rua=`).
4. **Transport & Bot Hardening:** `llm` and `media` subdomains lacked zone-level HTTP-to-HTTPS automatic 301 redirection, and Bot Fight Mode / AI Labyrinth were not engaged.

# Acceptance Criteria
- [x] `frontend/public/_headers` enforces `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` for all requests (`/*`).
- [x] `frontend/public/.well-known/security.txt` is created adhering to RFC 9116 standards, with contact mailboxes, expiry timestamp, canonical URL, and language declarations.
- [x] `frontend/public/_headers` serves `/.well-known/security.txt` with `Content-Type: text/plain; charset=utf-8` and cache-control.
- [x] Root `SECURITY.md` defines the security vulnerability disclosure and bug reporting policy.
- [x] `Caddyfile` specifies HSTS for `api.negolah.my` defense-in-depth.
- [x] `frontend/tests/pwa-navigate-fallback-denylist.test.ts` and `frontend/tests/security-headers.test.ts` assert HSTS and security.txt integrity.
- [x] DNS recommendations documented: Add apex TXT SPF (`v=spf1 include:amazonses.com ~all`) and update `_dmarc` with `rua=mailto:terryong30@gmail.com; aspf=r;`.
- [x] Operator runbook documented for Cloudflare Dashboard toggles (Always Use HTTPS, HSTS, Bot Fight Mode, AI Labyrinth, MFA).

# Technical Design & Contracts
- **`frontend/public/.well-known/security.txt`**:
  ```text
  Contact: mailto:terryong30@gmail.com
  Contact: mailto:support@negolah.my
  Expires: 2027-09-09T00:00:00.000Z
  Preferred-Languages: en, ms
  Canonical: https://negolah.my/.well-known/security.txt
  Policy: https://github.com/terryong31/nego-lah/blob/main/SECURITY.md
  ```
- **`frontend/public/_headers`**:
  ```text
  /.well-known/security.txt
    Content-Type: text/plain; charset=utf-8
    Cache-Control: public, max-age=604800

  /*
    Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
    ...
  ```
- **`Caddyfile`**:
  ```caddyfile
  api.negolah.my {
      header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
      ...
  }
  ```

# Test Scenarios
1. `tests/security-headers.test.ts`: Reads `_headers` and verifies `Strict-Transport-Security` is present on the root catch-all pattern and `/.well-known/security.txt` specifies `text/plain`.
2. `tests/pwa-navigate-fallback-denylist.test.ts`: Verifies `/.well-known/security.txt` is bypassed by service worker navigation fallback.
