---
id: SPEC-042
title: CORS Headers on Defense-Middleware Rejections
status: complete
priority: high
created: 2026-09-07
tags: [backend, security, cors, middleware]
assigned: agent
---

# Context & Objectives

Sellers could not upload new items: the browser console showed `Access to
fetch at 'https://api.negolah.my/admin/items' ... has been blocked by CORS
policy: No 'Access-Control-Allow-Origin' header is present`, even though
`https://negolah.my` is an allowed origin in `main.py`'s CORS config.

Two compounding bugs in `backend/main.py` / `backend/core/defense_middleware.py`:

1. **Middleware ordering.** `CORSMiddleware` is registered *before*
   `SecurityHeadersMiddleware` / `RequestDefenseMiddleware`. Starlette wraps
   middleware in reverse registration order, so the last-registered middleware
   ends up outermost. That made `RequestDefenseMiddleware` outermost and
   `CORSMiddleware` inward of it. `RequestDefenseMiddleware` short-circuits
   (returns a `JSONResponse` directly, without calling `call_next`) on an
   oversized `Content-Length` (413) or a malformed one / null-byte path (400).
   Those short-circuited responses never reach `CORSMiddleware`, so they carry
   no `Access-Control-*` headers — the browser reports a generic CORS failure
   instead of surfacing the real 413/400 status.
2. **Upload size allowance targets the wrong route.** `RequestDefenseMiddleware`
   only grants its larger `max_upload_content_length` (15 MB) to requests
   under `/admin/analyze-image`. The actual item-listing endpoints,
   `POST /admin/items` and `PUT /admin/items/{id}`, also accept one or more
   raw `UploadFile` images (`routes/admin/items.py`) but fall under the
   default 10 MB cap — a multi-photo listing from a phone camera realistically
   exceeds that, tripping bug #1's silent-CORS-failure path.

# Acceptance Criteria

- [x] Any response returned directly by `RequestDefenseMiddleware` (413
      payload-too-large, 400 bad `Content-Length`, 400 null-byte path/query)
      carries the correct `Access-Control-Allow-Origin` /
      `Access-Control-Allow-Credentials` headers when the request has an
      allowed `Origin`.
- [x] `POST /admin/items` and `PUT /admin/items/{id}` are allowed the same
      larger upload ceiling as `/admin/analyze-image` (15 MB), not the 10 MB
      default.
- [x] Existing CORS preflight tests and existing defense-middleware unit tests
      continue to pass unchanged.

# Technical Design & Contracts

**`backend/main.py`** — reorder `add_middleware` calls so `CORSMiddleware` is
registered *last* (making it the outermost middleware, ahead of
`SecurityHeadersMiddleware` and `RequestDefenseMiddleware`, in Starlette's
reverse-registration wrapping). This guarantees every response — including
ones a middleware short-circuits before the router — passes through
`CORSMiddleware` on the way out.

**`backend/core/defense_middleware.py`** — `RequestDefenseMiddleware`'s
`upload_path_prefix` constructor param accepts a `tuple[str, ...]` (in
addition to a single `str`, since `str.startswith` already supports both) and
defaults to `("/admin/analyze-image", "/admin/items")`.

No API contract changes — same routes, same status codes, just correct
headers and a size ceiling that matches what the endpoint actually needs.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `POST /admin/items` from an allowed `Origin`
  (`https://negolah.my`) with a `Content-Length` over the cap returns 413
  **and** `Access-Control-Allow-Origin: https://negolah.my`.
- [x] **Scenario 2:** Same request from a disallowed origin returns 413 with
  no `Access-Control-Allow-Origin` header (rejection still enforced).
- [x] **Scenario 3:** `RequestDefenseMiddleware` configured with a tuple
  `upload_path_prefix` allows the larger ceiling on both prefixes and still
  rejects a third, unlisted path at the default ceiling.
- [x] **Scenario 4:** `POST /admin/items` at the real default settings (no
  explicit prefix override) applies the 15 MB ceiling, not 10 MB.

# Implementation Files

- `backend/main.py` — middleware registration order
- `backend/core/defense_middleware.py` — `upload_path_prefix` default/tuple support
- `backend/tests/test_cors.py` — Scenarios 1–2
- `backend/tests/test_defense_middleware.py` — Scenarios 3–4
