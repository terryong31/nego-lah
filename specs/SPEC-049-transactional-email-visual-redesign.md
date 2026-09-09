---
id: SPEC-049
title: Transactional & Auth Email Visual Redesign ("Ledger" System)
status: complete
priority: medium
created: 2026-09-09
tags: [email, branding, design, jinja2, supabase]
assigned: agent
---

# Context & Objectives
Nego-Lah's seven email templates read as consumer-grade: body copy centred, emoji in
subject lines (`🎉`, `🚨`), up to four competing green highlights per message, and two
different grey palettes — `backend/templates/emails/base.html` uses slate
(`#0f172a` / `#64748b` / `#f8fafc`) while the Supabase auth templates use zinc.

This spec re-skins all seven templates + the shared layout onto **one token system**
("Ledger"): borderless, hairline rules as the only divider, system sans, muted ink,
a single emerald accent used only on the button and inline links, flush-left, and
dark-mode aware. Emoji are removed from all four transactional subject lines.

Supersedes the **visual-design** portions of SPEC-039 and SPEC-007. Keeps SPEC-021's
Jinja architecture (`base.html` + `components.html` macros + per-template files).
Rationale recorded in `docs/adr/0013-ledger-email-design-system.md`.

# Acceptance Criteria
- [x] `base.html` uses the Ledger tokens below, has a `@media (prefers-color-scheme: dark)`
      block + `color-scheme` meta, left-aligned content, and no card border / shadow / radius.
- [x] `components.html`: `status_badge` → `status_line`; `hero_amount` deleted;
      `detail_table(rows, total=None)` added; `cta_button` / `notice_box` / `quote_box`
      restyled to Ledger.
- [x] All 4 transactional templates recompose on the macros, carry an emoji-free
      informational preheader, and print a raw fallback URL under the button.
- [x] 3 Supabase templates re-skinned to Ledger, keeping every Go-template token
      (`{{ .Token }}`, `{{ .ConfirmationURL }}`, `{{ if }}`…`{{ end }}`) verbatim.
- [x] `backend/services/email_service.py`: 0 emoji in any subject line; public API unchanged.
- [x] `backend/templates/emails/` contains 0 references to `#0f172a`, `#64748b`, `#f8fafc`, `#f97316`.
- [x] Brand icon rendered at `width="24" height="24"`, `object-fit:contain`, no `border-radius`.
- [x] `mise run test:backend` (1220 passed) and `mise run lint` pass with 0 errors.

# Technical Design & Contracts
**Ledger tokens (light / dark):**
- ground + card `#f4f4f2` / `#0a0a0a` (card borderless, same colour as body)
- ink `#1a1a1e` / `#f2f2f3` · ink-soft `#4b4b52` / `#b0b0b6` · muted `#78787f` / `#82828a`
- hairline `#dededa` / `#232323` (the only divider)
- accent (links, total) `#047857` / `#34d399`
- brand (button fill only) `#10b981`, border `#059669`
- danger (human-transfer status + callout only) `#b91c1c` / `#f87171`

**Type:** system sans. h1 20px / 600 / −0.02em, left. Body 15px / 1.62. Labels 12–13px.
**Button:** full-width block, `#10b981` fill, 3px radius, 13px 20px pad, inline
`color:#ffffff !important; text-decoration:none !important`, table-wrapped.

**Subjects (`email_service.py`):**
- receipt: `Payment confirmed — {item_name}`
- sale: `You sold {item_name} for RM{amount:.2f}`
- unread message: `New message from the seller` (+ ` — {item_name}` when known)
- human transfer: `Action needed: chat handed to you — {user_display}`

**Brand icon:** `frontend/public/icon-512.png` is already synced to Supabase Storage
`images/branding/logo.png` by `backend/scripts/sync_cdn_assets.py` (`mise run cdn:sync`).
Per ADR 0010 it stays on Supabase Storage, not R2. Templates keep referencing it via
`get_brand_logo_url()` / the hard-coded URL — only the render size/treatment changes.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1 (`test_email_service.py`, Red first):** status strings updated —
      `Item sold` / `Payment received` / `New message` / `Needs your response`;
      `test_email_template_renders_cdn_brand_logo` asserts `width="24"`.
- [x] **Scenario 2 (`test_email_service.py`):** new assertions — `"🎉"` absent from the
      sale subject, `"🚨"` absent from the human-transfer subject.
- [x] **Scenario 3 (`test_email_service.py`):** button assertions still hold —
      `#10b981`, `color: #ffffff`, no `#f97316`.
- [x] **Scenario 4 (`test_admin_session.py::test_render_otp_email_html`):** still green —
      OTP token, action link, and `"Nego"` present after the magic-link re-skin.

# Rollout — Supabase auth templates (`supabase config push`)

Pushed to the staging and prod projects on 2026-09-09 via
`supabase config push --project-ref <ref>`:

- **staging** — templates + subjects synced; `additional_redirect_urls` gained the
  `/**` wildcards from `config.toml`. Auth config now "up to date".
- **prod** (`[remotes.prod]` override) — templates + subjects synced. `site_url`
  was already `https://negolah.my` (unchanged). `additional_redirect_urls` went
  from the single `["https://www.negolah.my"]` to the correct 4-entry set
  (`negolah.my`, `www.negolah.my`, each + `/**`) — no dev origins, per Terry.

`config push` **resets any auth field absent from `config.toml` to the CLI
default** (learned the hard way — a partial push wiped staging's redirect list
and `enable_confirmations`, then restored). So the full `[auth]` block must stay
in `config.toml`, and per-environment differences go in `[remotes.<label>]`
override blocks (added `[remotes.prod]` locking prod to the real domain only).
`config push` does **not** touch `[auth.external.*]` — Google OAuth was
unaffected on both.

Two extra changes made during rollout:
- **OTP out of the subject line.** `magic_link` subject is now
  `"Your Nego-lah verification code"` (no `{{ .Token }}`) — lock-screen / mail-log
  exposure + open-rate/deliverability hit. The code stays in the body + preheader.
  Same fix applied to the Resend OTP-fallback subject in `admin_session.py`.
- **`[remotes.prod]`** block in `config.toml` — prod `site_url` +
  `additional_redirect_urls` overrides (real domain only, no dev origins).

# Implementation Files
- `specs/SPEC-049-transactional-email-visual-redesign.md` - This spec
- `docs/adr/0013-ledger-email-design-system.md` - Decision record
- `backend/templates/emails/base.html` - Ledger tokens, dark mode, left-align, borderless
- `backend/templates/emails/components.html` - macros: `status_line`, `detail_table`, restyled `cta_button` / `notice_box` / `quote_box`
- `backend/templates/emails/{purchase_receipt,seller_sale_alert,unread_message,human_transfer_alert}.html` - recomposed
- `backend/services/email_service.py` - emoji-free subjects
- `supabase/templates/{magic_link,recovery,confirmation}.html` - Ledger re-skin
- `supabase/config.toml` - magic-link subject (OTP removed); `[remotes.prod]` auth override
- `backend/admin_session.py` - bare OTP fallback HTML tone; OTP removed from fallback subject
- `backend/tests/test_email_service.py` - updated + new assertions
