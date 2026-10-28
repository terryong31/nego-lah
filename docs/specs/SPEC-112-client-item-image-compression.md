---
id: SPEC-112
title: Client-Side Item Photo Downscaling & Caddy Upload Limit Alignment
status: complete
priority: high
created: 2026-10-29
tags: [catalog, frontend, upload]
assigned: agent
---

# Context & Objectives

Uploading 6 high-resolution phone photos (~3 MB each, ~18 MB total) in the Admin Console fails on
**Create item** (`POST /admin/items`) with HTTP 413 (`Payload too large. Maximum permitted size is
15728640 bytes`), even though:
1. The upload dropzone explicitly states `"PNG, JPG or HEIC — compressed automatically"`.
2. **Detect & fill** (`POST /admin/analyze-image/stream`) succeeded on the exact same 6 photos.

Root causes:
- `useItemAnalysis.ts` downscales photos in the browser (`maxEdge = 1024`, JPEG `0.82`) before
  uploading to `/admin/analyze-image/stream`, shrinking 6 phone photos to ~900 KB total.
- `AdminItemFormModal.vue` (`submitItem()`) appends raw, uncompressed `img.file` objects directly to
  `FormData` on `POST /items` and `PUT /items/{id}`. Because `RequestDefenseMiddleware` rejects
  multipart payloads over `15,728,640` bytes (15 MB) before the request reaches `normalize_image()`
  in `backend/core/images.py`, multi-photo raw uploads fail with HTTP 413.
- In addition, `Caddyfile` sets `request_body { max_size 10MB }`, which is stricter than
  `RequestDefenseMiddleware`'s 15 MB upload ceiling (`max_upload_content_length = 15 * 1024 * 1024`).

# Acceptance Criteria

- [x] Shared browser utility `downscaleImage(file, options)` in `frontend/app/utils/downscaleImage.ts`
      decodes images via `createImageBitmap`, scales the longest edge to `maxEdge` (default `2048`,
      matching `MAX_ITEM_EDGE` in `backend/core/images.py`), encodes to JPEG (`quality = 0.82`), and
      returns a smaller `File` (or the original `File` when already small, undecodable, or larger
      after re-encoding).
- [x] `useItemAnalysis.ts` delegates to `downscaleImage(file, { maxEdge: 1024 })`.
- [x] `AdminItemFormModal.vue` (`submitItem()`) downscales all `new` staged images via
      `downscaleImage(img.file)` before appending them to `FormData` on both `POST /items` and
      `PUT /items/{id}`.
- [x] `Caddyfile` `request_body` `max_size` is raised from `10MB` to `15MB` to match
      `RequestDefenseMiddleware.max_upload_content_length`.

# Technical Design & Contracts

- `downscaleImage(file: File, options?: { maxEdge?: number, quality?: number, sizeFloor?: number }): Promise<File>`:
  - Defaults: `maxEdge = 2048`, `quality = 0.82`, `sizeFloor = 400_000`.
  - If `createImageBitmap` or `document` is unavailable, returns `file`.
  - If `scale === 1` and `file.size < sizeFloor`, returns `file` untouched.
  - Otherwise draws onto a `<canvas>` of `Math.round(width * scale)` × `Math.round(height * scale)`,
    encodes via `canvas.toBlob(resolve, 'image/jpeg', quality)`, and wraps the blob into a `File`
    with a `.jpg` extension if `blob.size < file.size`. Always closes the `ImageBitmap` in `finally`.
- `Caddyfile`: `request_body { max_size 15MB }`.

# TDD Scenarios

- `downscaleImage` shrinks a `4032×3024` file to `2048×1536` JPEG `File` when the encoded blob is smaller.
- `downscaleImage` re-encodes a file whose dimensions are `<= maxEdge` when `file.size >= sizeFloor`.
- `downscaleImage` returns the original `File` when `scale === 1` and `file.size < sizeFloor`, when
  `createImageBitmap` is unavailable or throws (e.g. unsupported HEIC in browser), or when the
  re-encoded blob is not smaller than the input.
- `AdminItemFormModal.vue` passes staged new files through `downscaleImage` on both `POST /items`
  and `PUT /items/{id}` while preserving photo order.
- `test_edge_proxy_config.py` asserts `Caddyfile` `max_size` is `15MB`.

# Implementation Files

- `frontend/app/utils/downscaleImage.ts`
- `frontend/app/composables/useItemAnalysis.ts`
- `frontend/app/components/admin/AdminItemFormModal.vue`
- `Caddyfile`
- `frontend/tests/utils/downscaleImage.test.ts`
- `frontend/tests/components/admin/AdminItemFormModal.test.ts`
- `backend/tests/test_edge_proxy_config.py`
