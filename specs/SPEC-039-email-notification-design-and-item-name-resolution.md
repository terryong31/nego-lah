---
id: SPEC-039
title: Transactional Email Design Overhaul & Item Name Resolution
status: complete
priority: high
created: 2026-09-05
tags: [backend, email, stripe, fulfillment, branding]
assigned: agent
---

> Renumbered from SPEC-018: three pairs of specs had been filed under the same
> number, which broke traceability. Content unchanged.

# Context & Objectives
In Nego-Lah's admin/seller sale notification emails:
1. The item name displayed in the subject and table body was resolving to generic `"Item"` instead of the actual item name because Stripe PaymentLink metadata omitted `item_name`, and fulfillment did not query the database as a fallback.
2. The email template relied on mismatched brand colors (orange `#f97316` and amber `#fef3c7`) rather than Nego-Lah's primary emerald green profile (`#10b981`, `#059669`).
3. Call-to-action (CTA) buttons lacked inline `#ffffff` styling on the anchor tag, causing email clients (such as Gmail) to render visited links in default purple (`#551a8b`) over the background.

This specification establishes:
- Automated item name resolution in Stripe PaymentLink creation, webhooks, payment confirmation, and fulfillment database fallbacks.
- Complete overhaul of transactional email templates (`send_seller_sale_alert`, `send_purchase_receipt`, and `send_unread_message_email`) adhering to modern e-commerce gold standards (single-column responsive card, hidden preheaders, emerald brand tokens, inlined bulletproof button styling).

# Acceptance Criteria
- [x] `backend/agent/tools/payment.py` sets `"item_name": item_name` in `stripe.PaymentLink.create` metadata.
- [x] `backend/payment/fulfillment.py` detects missing, empty, or `"Item"` names and resolves the actual name from the `items` table using `item_id`.
- [x] `backend/services/email_service.py` templates use Nego-Lah brand colors (emerald green `#10b981` / `#059669`, background `#fafafa`, card `#ffffff`, slate text `#09090b` / `#111827`) and contain 0 references to orange `#f97316`.
- [x] All CTA buttons in `backend/services/email_service.py` contain inline `color: #ffffff !important; text-decoration: none !important;` and `background-color: #10b981` to prevent visited link purple rendering.
- [x] All backend tests pass, lint passes with 0 errors.

# Technical Design & Contracts
- **Stripe Metadata Contract**:
  ```python
  metadata={
      "item_id": item_id,
      "user_id": user_id,
      "item_name": item_name,
  }
  ```
- **Fulfillment Fallback Contract**:
  ```python
  if (not item_name or item_name.strip().lower() == "item") and item_id:
      item_row = admin_supabase.table('items').select('name').eq('id', item_id).single().execute()
      if item_row and item_row.data and item_row.data.get('name'):
          item_name = item_row.data['name']
  ```
- **Email Design Tokens**:
  - Primary Brand Green: `#10b981` (CTA button, logo highlight)
  - Dark Emerald: `#059669` / `#047857` (Amount text, badge text)
  - Badge Background: `#ecfdf5`, Border: `#a7f3d0`
  - Text Primary: `#09090b` / `#111827`, Secondary: `#52525b`, Muted: `#71717a`
  - Card Background: `#ffffff`, Border: `#e4e4e7`

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1 (`test_agent_tools_payment.py`):** Verify `create_checkout_link` passes `item_name` in Stripe PaymentLink metadata.
- [x] **Scenario 2 (`test_payment_fulfillment.py`):** Verify `fulfill_purchase` resolves actual item name from Supabase `items` table when `item_name="Item"`.
- [x] **Scenario 3 (`test_email_service.py`):** Assert email templates contain `#10b981`, `#059669`, inline `color: #ffffff`, and zero instances of `#f97316`.

# Implementation Files
- `specs/SPEC-039-email-notification-design-and-item-name-resolution.md` - Specification
- `backend/agent/tools/payment.py` - PaymentLink metadata
- `backend/payment/fulfillment.py` - Database item name fallback
- `backend/payment/webhooks.py` - Webhook item name resolution
- `backend/routes/payment.py` - Payment confirm route item name resolution
- `backend/services/email_service.py` - Transactional email templates
- `backend/tests/test_email_service.py` - Email styling assertions
- `backend/tests/test_payment_fulfillment.py` - Fulfillment fallback tests
- `backend/tests/test_agent_tools_payment.py` - Payment link metadata tests
