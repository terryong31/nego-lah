1. ruff check
2. ci checks
3. unit tests and coverage
4. integration testing
5. llm performance testing and benchmark
6. email sending integration
7. frontend analytics, tracing, logging
8. integrate i18n, zod validation
9. turn chat page into splitter
10. turn landing page into actual landing page. no featured items
11. investigate Sentry issue 7711492289 (see Sentry dashboard)
12. Email UX. User successful purchase will send email for receipt
13. SSE for real time notification when seller sent a message to the user
14. Email for unread messages
15. When seller offered a lower price, show price cut on the listing itself
16. After paid on stripe, show successful payment screen and redirect user to chat
17. the successful payment chat do not use markdown format 
18. deploy to cloudflare pages
19. when paid notify seller via email
20. [x] SPA loading template html
21. [x] Favicon, SEO Meta, Top logo
22. Design Refactor landing page
23. Fix rate limiting ui for chat
24. fix image editing support
25. [x] Real time chat broken
26. [x] Implement human in the loop (transfer to admin console + send email)
27. [x] \n do not render as multiple chat bubble when client writes message with line breaks
28. [x] Mobile support for console chat page
29. [x] After payment, turn the checkout link text message to disabled
30. [x] User client-side notification when seller/agent sent message
31. [x] Optimize build time and docker cache
32. [x] Optimize ci/cd pipeline for using gold standard
33. [x] check i18n coverage ensure everything is i18n covered
34. [x] integrate security audit and check using static analysis library and running defense middleware
35. [x] put video and branding icon in supabase storage as cdn. branding icon for email logo and video for faster loading (is it possible to make video streaming?)
36. [x] support@negolah.my not sent to my email via relay
37. [x] dont send email for every unseen message for users from seller, 5 min buffer, one digest email (SPEC-052/ADR-0016: seller messages to an offline buyer queue in Redis; a sweeper flushes ONE email once the oldest has waited 5 min. The buyer reading their chat or sending a message cancels it. Tune UNREAD_DIGEST_DELAY_SECONDS; DISABLE_UNREAD_DIGEST=1 opts out)
38. [x] user still do not receive email upon payment successful (SPEC-048: pipeline verified working — negolah.my verified in Resend, real receipt delivered 2026-09-08; hardened: checkout pre-fills account email, _finalize_won_sale falls back to account email, receipt-send failure now fires a Sentry alert. `mise run email:diagnose`. RESEND_FORWARD_FROM set to "Nego-Lah <receipts@negolah.my>" in Infisical /Backend dev+prod on 2026-09-09)
39. [x] agent pass to seller is broken, doesnt activate the hitl properly (SPEC-046: HITL was activating server-side; the console badge went stale. /admin/chats now returns ai_enabled/admin_intervening; the console re-syncs from GET /users/{id}/ai on any system notice instead of matching notice text)
41. [x] rewrite html templates to make it look professional, maybe need to use shadcn style (SPEC-049/ADR-0013: all 7 email templates + Supabase auth templates re-skinned onto one "Ledger" token system — borderless, hairline rules, system sans, single emerald accent, dark-mode aware; emoji removed from transactional subject lines; SPEC-021 Jinja macro architecture kept)
42. [x] refine the console chat page, add filter, sorting, search (SPEC-046: sort by recent activity / unread first / most messages, client-side name+message search, filter unchanged)
43. [x] do not perform 50% price cut between the min_price and current nego price (SPEC-047/ADR-0011: below floor → hold, no concession; above floor → concede 25% of the gap snapped to RM5, whole numbers only; tune COUNTER_CONCESSION_RATIO / COUNTER_STEP_RM in agent/config.py)
44. [x] agent nego price ui should change together with the buy button, not the original price (SPEC-047: /payment/checkout now charges min(listed, negotiated) clamped to the floor — the pinned-header Buy Now button honours the haggled price; no UI change)
45. [x] optimize seller agent flow to reduce cost + evaluate it (SPEC-059/ADR-0020: item photos no longer ride along on every turn — a text knowledge card built from the listing replaces them, since `items.description` was written from those same photos at listing time; photos return only for a visual question, a buyer upload, or a listing with no description. History window 50 → AGENT_HISTORY_TURNS (20). `agent/cost.py` prices real usage_metadata. `mise run eval:agent` scores 12 golden scenarios for quality + tokens + latency + RM. NOTE: ragas was attempted and rejected — every release through 0.4.3 hard-imports a langchain_community module that no longer exists, and adding it downgraded PRODUCTION deps (rich 15→14.3.4, openai 3.7→3.3) via uv's shared resolution; replaced with a short LLM judge, `_judge_relevancy` is the seam to swap back)
46. [x] COD not supported in-app; hand to Terry; state FCFS (SPEC-055: COD_POLICY in agent/config.py is spliced into SELLER_PERSONA — explains COD isn't handled here, calls transfer_to_human with reason "Cash-on-delivery arrangement requested", and always states that only a PAID order holds an item, so a COD arrangement is cancelled if someone pays first)
47. [x] Update readme (rewritten against the current system: email/digest, image pipeline, defence-in-depth and HITL features; corrected the stale Gemini model, agent tool names and .env.example claim; added Background Workers + Operational Tasks sections and a real ADR table. ADR index backfilled with 0014-0017)
48. [x] Cloudflare Security Center findings remediation (SPEC-050/ADR-0014: HSTS in _headers + Caddyfile, RFC 9116 security.txt, SECURITY.md policy; DNS SPF & DMARC + Cloudflare zone hardening runbook)
49. [x] Integrate postage: admin uploads tracking number + courier, buyer gets an email (SPEC-057/ADR-0019: PUT /admin/orders/{id}/shipment records courier + tracking, stamps shipped_at, moves the order to shipped, emails the buyer and posts in their chat — one act, three notifications. Courier registry in domains/catalog/shipping.py builds the tracking URL from 8 Malaysian carriers and tolerates the seller's shorthand ('jnt' → 'J&T Express'). Console gets a postage form in the order's expanded row; `notify: false` for correcting an already-announced shipment)
50. [x] AI updates the user about shipping status + chat notify (SPEC-057: folded into `check_user_orders` rather than a new tool — same question, and every extra tool costs its schema in every prompt of every turn. Reports courier, tracking number and a track link; says nothing rather than 'Courier: None'. Marking an order delivered notifies once, only on the transition. Chat notices are plain text with a bare URL, never markdown — a markdown link would render as a 'Secured by Stripe' PayCard)
51. [x] Image auto-compression on upload + HEIF support (SPEC-054/ADR-0017: core/images.py decodes every upload, converts HEIC/HEIF, caps the long edge (2048 listings / 512 avatars), re-encodes to JPEG or WebP-with-alpha, bakes in EXIF orientation and strips metadata incl. GPS. Extension and content-type now come from the decode, never the filename — SPEC-044's guarantee finally extended to listings)
52. [x] Common knowledge base instead of ingesting the image on every query (SPEC-059/ADR-0020: see 45 — the knowledge card IS that common base. On the model swap: GEMINI_MODEL is already env-overridable, so it needs no code change; `mise run eval:agent -- --model <other>` prints pass rate per category beside RM/conversation. Watch the CONFIDENTIALITY row, not the price — a cheaper model that recites min_price to a buyer loses more on one sale than it saves in a month)
54. [x] Security vulnerability remediation: CORS pages.dev restriction to nego-lah.pages.dev, AI agent shipping info buyer_id scoping, PII log masking (SPEC-051/ADR-0015)
55. [x] mark as read on admin console doesnt work (SPEC-053: `unread` was derived from last_role=='human', so only REPLYING could clear it — there was no read state to mark. chat_settings.admin_last_read_at is now a real watermark; POST /admin/chats/{id}/read sets or clears it, opening or replying to a thread stamps it, and each row has a mail/mail-open toggle)
57. [x] Security audit remediation, 8 findings (SPEC-056/ADR-0018: refund moved under the CSRF-protected admin router; collect_shipping_info fails closed on a missing user_id; email change costs the password and now actually sends a confirmation link; only buy./checkout.stripe.com may render as a PayCard; request bodies are metered on the wire, not just by Content-Length; SSE authorises with a 30s single-use ticket instead of the access token in the URL; account deletion re-authenticates and brute force is throttled per-account; core/database.py's duplicate service-role clients deleted. Anti-patterns written up in docs/SECURITY_ANTI_PATTERNS.md)
60. [x] unread chip stays on the storefront after the buyer has read the chat (SPEC-066/ADR-0022: `messages.created_at` was `datetime.now()` — naive local time in a `timestamptz` column, so on a UTC+8 box every row was filed eight hours in the future and no `now(UTC)` watermark could get past it; the console's dot had the same disease. Timestamps are aware now, and unread state ignores anything dated more than a minute ahead — a mis-stamped row is history, not news — which clears the rows already in the table without the forward-stamping trick that would have muted the badge for eight hours. Second hole, same symptom: leaving or backgrounding /chat now stamps, because the agent's reply to the buyer's own turn lands after the arrival stamp and over a stream the badge never sees)

40. do etl pipeline from langsmith, sentry and google analytics and wire into dashboard to see user activity
53. Integrate discord/telegram for admin notifications
56. Make VueTour for user onboarding
58. Integrate grafana for server monitoring
59. investigate why this app runs so hot on my laptop
