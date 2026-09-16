---
id: SPEC-009
title: "SPEC-009: Real-Time SSE Notifications, Purchase Email Receipts & Post-Purchase UX"
status: "Draft"
created_at: "2026-09-04"
tags: ["notifications", "email", "sse", "payment", "ux", "ci-cd"]
---

# SPEC-009: Real-Time SSE Notifications, Purchase Email Receipts & Post-Purchase UX

## 1. Context & Motivation
Following successful payment negotiations and seller communications, users require a seamless, responsive lifecycle:
1. **Email Receipts & Alerts**: Buyers must receive an immediate receipt email upon completed Stripe payment, and the seller must receive an email notification alerting them of the sale.
2. **Real-Time Notification & Badging**: When the seller sends a message to a buyer who is browsing other pages, the buyer must immediately receive an SSE notification, a toast notification, and visual `<UChip>` badges on the top nav chat icon and user avatar.
3. **Unread Message Email Fallback**: When an offline user has unread messages, an email notification is dispatched.
4. **Negotiated Price Cut on Listing**: When the AI or seller agrees to a lower price for a buyer, the listing view must reflect the price cut (strikethrough original price + highlighted discounted price).
5. **Post-Payment UX**: After successful Stripe checkout, the user lands on a clear confirmation screen and is automatically routed to `/chat` to provide shipping information, with the bot's thank-you prompt formatted in clean plain text without markdown asterisks.
6. **Cloudflare Pages CI/CD Pipeline**: Streamlined GitHub Actions build and deploy pipeline with all requisite build environment parameters.

---

## 2. Acceptance Criteria

### A. Purchase Emails (Buyer Receipt + Seller Alert)
- [ ] `fulfill_purchase` invokes `send_purchase_receipt_email(buyer_email, order)` delivering an HTML receipt via Resend.
- [ ] `fulfill_purchase` invokes `send_seller_sale_alert_email(seller_email, order)` alerting the seller with buyer email, item name, and price.

### B. Real-Time SSE Notifications & Nav Badging
- [ ] Backend provides an authenticated SSE endpoint `GET /chat/notifications/stream` streaming `event: message` when the seller posts a message to `user_id`.
- [ ] `AppHeader.vue` listens to notifications:
  - If current route is NOT `/chat`: triggers a toast alert and renders `<UChip>` on the chat icon and user avatar.
  - When user navigates to `/chat`, unread status clears and chips disappear.

### C. Unread Message Email
- [ ] When a seller sends a message, if the buyer is not connected to the live notification stream, an email notification is scheduled/sent to the buyer.

### D. Listing Price Cut Display
- [ ] When an agreed lower price exists for an item in `payment_state`, `/items/:id` returns `discounted_price`.
- [ ] `pages/items/[id].vue` and `ItemCard.vue` display the original price with a strikethrough and the new discounted price with a badge.

### E. Post-Payment UX & Plain-Text Chat
- [ ] `checkout/success.vue` displays the success card and redirects the user to `/chat?item_id={itemId}` after a brief countdown (with an instant "Go to Chat" button).
- [ ] Post-purchase thank-you prompt in `fulfillment.py` uses clean plain text without markdown `**` bolding.

### F. CI/CD Cloudflare Pages Deployment
- [ ] `.github/workflows/deploy.yml` sets necessary environment variables during `bun run generate` before running `pages deploy`.

---

## 3. Test Scenarios
1. `test_payment_fulfillment.py`: Verifies buyer receipt and seller alert email dispatches upon fulfillment.
2. `test_fulfillment_plain_text_message.py`: Verifies thank-you message contains no markdown asterisks.
3. `test_routes_chat_notifications.py`: Tests SSE stream connection and message broadcasting.
4. `frontend/tests/components/AppHeader.test.ts`: Verifies UChip renders when unread messages arrive while off `/chat`.
5. `frontend/tests/pages/checkout/success.test.ts`: Verifies automatic redirect timer and link to `/chat`.
6. `frontend/tests/pages/items/id.test.ts`: Verifies price strikethrough when `discounted_price` is present.
