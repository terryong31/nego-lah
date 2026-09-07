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
11. investigate this issue https://nego-lah.sentry.io/issues/7711492289/events/8c74d14fb3a74883854327f7f9d7622e/?project=4511683402268672&referrer=discover-events-table
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
36. support@negolah.my not sent to my email via relay