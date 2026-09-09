# 13. One "Ledger" Design System for All Transactional and Auth Emails

- Status: Accepted
- Date: 2026-09-09
- Deciders: Terry (owner), AI Agent
- Supersedes: the visual-design portions of SPEC-039 (transactional email design) and
  SPEC-007 (auth template markup). The Jinja architecture from SPEC-021 is unchanged.
- Related: ADR 0012 covers the *deliverability* side (sender mailbox, failure alerting);
  this ADR is purely the *visual* system. Both are consumed by SPEC-049.

## Context

Nego-Lah sends seven templated emails: three Supabase auth templates
(`magic_link`, `recovery`, `confirmation`) and four transactional templates
(`purchase_receipt`, `seller_sale_alert`, `unread_message`, `human_transfer_alert`).
They had drifted apart:

- The transactional `base.html` centred all body copy, wrapped a single content block
  in a bordered + shadowed card, and stacked up to four emerald elements per message
  (pill badge, 32px hero amount, left-border notice box, button).
- Subject lines carried emoji (`🎉 Item Sold`, `🚨 Human Transfer Required`).
- `base.html` used a **slate** palette (`#0f172a` / `#64748b` / `#f8fafc`); the auth
  templates used **zinc** (`#09090b` / `#52525b` / `#fafafa`). Two greys, no system.
- The transactional base had no dark-mode handling; the auth templates did.

Half of these emails are read by the operator and by sellers, next to Stripe, bank,
and Supabase mail in the same inbox.

### Decision Drivers

- **One identity.** Every Nego-Lah email should look like it came from the same company.
- **Trust over personality.** These are receipts, codes, and alerts — not marketing.
- **Never dates.** The design should still look right in three years.
- **Dark mode is not optional.** Apple Mail auto-inverts un-handled light templates.

## Considered Options

Three directions were built out and previewed across all seven templates, light and dark
([Email Design Directions artifact](https://claude.ai/code/artifact/b4111ad1-2ad5-4ef8-b9e9-ac125fb1bb27)):

1. **Ledger** — borderless, inset hairline rules as the only divider, system sans, muted
   ink, one emerald accent on the button + links. After Stripe and Apple receipts.
2. **Console** — bordered card, IBM Plex Mono for labels / metadata / timestamps, emerald
   status dots, tight inline button. After Linear, GitHub, Vercel.
3. **Editorial** — Fraunces serif display headline, warm paper, soft shadow, generous air,
   the receipt total gets one serif moment. A premium consignment house.

## Decision

We chose **Option 1: Ledger**, applied as a single token set consumed by `base.html`,
the `components.html` macros, and all seven templates.

- **Tokens:** ground/card `#f4f4f2` / `#0a0a0a` · ink `#1a1a1e` / `#f2f2f3` · ink-soft
  `#4b4b52` / `#b0b0b6` · muted `#78787f` / `#82828a` · hairline `#dededa` / `#232323` ·
  accent `#047857` / `#34d399` · brand button `#10b981` (border `#059669`) ·
  danger `#b91c1c` / `#f87171`.
- **Structure:** no card border, shadow, or radius — the card is the same colour as the
  body. Inset 1px hairlines divide blocks. Logo top-left at 24px, wordmark "Nego-lah".
- **One accent.** Emerald appears only on the button fill and inline links. The pill
  badge and hero amount are gone; status is a small label beside a 22×2px rule.
- **Semantic ≠ brand.** `human_transfer_alert` uses `danger` red for its status line and
  callout and no emerald anywhere except the button.
- **Emoji removed** from all four transactional subject lines.
- **Dark mode** via `@media (prefers-color-scheme: dark)` + a `color-scheme` meta on every
  template.
- **Fallback URL** printed under the button in every action email.

Console was the runner-up (it mirrors the `/_console` product surface well), but Ledger
won on "disappears next to a bank email" — the right instinct for money and security mail.
Editorial's serif headline was judged too expressive for admin alerts.

## Consequences

- **Positive:** One palette, one type scale, one set of macros. Every email is dark-mode
  correct. Subjects pass stricter spam heuristics. The design has no trend to age out of.
- **Negative:** `status_badge` → `status_line` and the removal of `hero_amount` are
  breaking macro changes; the four templates and their tests are updated in lockstep.
- **Neutral:** The brand icon (`frontend/public/icon-512.png` → Supabase Storage
  `images/branding/logo.png`, per ADR 0010) is unchanged — only its render size (32→24)
  and treatment (drop the `border-radius` that clipped the speech-bubble tail).
- **Follow-on:** If Supabase's `invite` / `email_change` / `reauthentication` templates
  are ever enabled, they adopt this same system.
