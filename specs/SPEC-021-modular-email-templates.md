---
id: SPEC-020
title: Modular Email Template Architecture with Jinja2
status: complete
priority: medium
created: 2026-09-05
tags: [email, jinja2, refactor, architecture, templates]
assigned: agent
---

# Context & Objectives
In `backend/services/email_service.py`, all transactional HTML emails (purchase receipts, seller sale alerts, unread message alerts, and human transfer alerts) were embedded as monolithic multiline f-strings spanning over 450 lines of code. This tightly coupled presentation with business logic, made template modifications brittle, prevented reusability of brand components, and bloated the service file.

This specification establishes a clean, modular, and maintainable email templating architecture using **Jinja2** with template inheritance and reusable component macros, separating presentation entirely from Python logic.

# Acceptance Criteria
- [x] `jinja2` is configured with deterministic template path resolution (`Path(__file__).resolve().parent.parent / "templates" / "emails"`).
- [x] Base layout template `base.html` defines bulletproof responsive structure, brand header, typography, container card, and footer.
- [x] Macros defined in `components.html` provide standardized components:
  - `status_badge`: Pill badges with semantic color variants (`success`, `danger`, `warning`).
  - `cta_button`: Bulletproof centered table-wrapped button with brand `#10b981` background and inline white link overrides.
  - `hero_amount`: Large headline currency formatting (`RMxxx.xx`).
  - `details_table`: Structured key-value table for order/escalation details.
  - `notice_box`: Action callout box with accent left border.
- [x] Individual transactional templates extend `base.html`:
  - `purchase_receipt.html`: Buyer purchase confirmation.
  - `seller_sale_alert.html`: Seller notification of purchase.
  - `unread_message.html`: Buyer notification of offline unread chat message.
  - `human_transfer_alert.html`: Urgent admin alert for human-in-the-loop chat escalation.
- [x] `backend/services/email_service.py` is stripped of inline HTML, delegating to `render_email_template(template_name, context)` while retaining identical public API signatures.
- [x] All existing email tests in `backend/tests/test_email_service.py` pass without regression.
- [x] Full backend test suite passes and `mise run lint` passes with 0 errors.

# Technical Design & Directory Structure
```
backend/
├── templates/
│   └── emails/
│       ├── base.html
│       ├── components.html
│       ├── purchase_receipt.html
│       ├── seller_sale_alert.html
│       ├── unread_message.html
│       └── human_transfer_alert.html
└── services/
    └── email_service.py
```

# Test Scenarios
- [x] `test_email_service.py`: Verify all four transactional email senders render their respective templates, populate context variables, and deliver successfully via Resend.
- [x] `test_email_templates_render`: Test standalone template rendering with Jinja2 to assert HTML structure, styling tokens, and escaping.
