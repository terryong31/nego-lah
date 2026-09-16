---
id: SPEC-012
title: Admin Item Image Editing
status: complete
priority: high
created: 2026-09-05
tags: [frontend, backend, admin, items, storage]
---

# Context & Objectives
The admin "Edit item" modal can only change text and prices — it renders the hint
*"Image editing isn't supported here — existing images are kept."* Fixing a bad
thumbnail today means deleting the listing and re-uploading it, which loses the
item id (and with it, its order/chat history).

Bring the edit modal to parity with "Upload item": one photo grid that shows the
listing's current photos alongside newly added ones, supporting add, remove and
drag-to-reorder, with the first photo as the thumbnail.

# Acceptance Criteria
- [x] The edit modal renders the same photo grid as create, seeded with the item's stored photos in their stored order.
- [x] Photos can be added (picker or drop), removed, and reordered while editing; position 0 is badged "Thumbnail".
- [x] Saving an edit persists the exact displayed order, mixing kept and newly uploaded photos.
- [x] Photos removed while editing are deleted from Supabase Storage; a storage failure never fails the save.
- [x] Saving requires at least one photo, when editing as well as creating.
- [x] Object URLs are created only for newly staged files and revoked on remove/close; stored public URLs are never revoked.

# Technical Design & Contracts

## `PUT /admin/items/{item_id}` — JSON body → `multipart/form-data`
Browsers cannot send files as JSON, and splitting fields and photos across two
requests risks a half-applied edit, so the route takes one multipart body:

| field | type | notes |
|---|---|---|
| `name` `description` `condition` | Form str? | as before |
| `price` `min_price` | Form float? | as before |
| `translations` | Form str? | JSON object |
| `images_order` | Form str? | JSON array of tokens, in display order |
| `new_images` | File[]? | uploads referenced by the order tokens |

An `images_order` token is either the **public URL of a photo the item already
has**, or **`"new:<n>"`** naming the nth file in `new_images`. Tokens matching
neither are dropped, so a stale client can never write a foreign URL into the
row. Omitting `images_order` leaves `image_path` untouched.

`UpdateItemSchema` is removed — the route it modelled no longer takes a JSON body.

## `items.sync_item_images(item_id, ordered, new_images) -> str | None`
Rebuilds `image_path` (a `{filename: url}` map whose insertion order *is* the
display order): reads the current map, uploads each new file to
`items/{item_id}/{uuid8}.{ext}` (unique names, so a re-upload never overwrites a
still-referenced object), resolves tokens in order, then removes the storage
objects for photos that dropped out. Returns the JSON string for `update_item`,
or `None` if the rebuild failed.

## `AdminItems.vue`
`PendingImage` becomes a tagged union — `{ kind: 'new', file, url }` (object URL)
or `{ kind: 'existing', url }` (stored URL) — so `releaseImages`/`removeImage`
revoke only what they created. `openEdit` seeds the grid from `image_path`;
`canSubmit` requires a photo in both modes.

# Test-Driven Development (TDD) Scenarios
- [x] **Backend 1:** `sync_item_images` keeps a subset in the requested order and returns a matching JSON map.
- [x] **Backend 2:** `"new:<n>"` tokens upload to `items/{id}/…` and land at the requested position; unknown tokens are dropped.
- [x] **Backend 3:** Photos dropped from the order are removed from storage; a `remove()` that raises still returns the new map.
- [x] **Backend 4:** A storage/upload exception returns `None`; the route then 500s without touching the row.
- [x] **Backend 5:** `PUT /admin/items/{id}` with multipart fields calls `update_item` with `images=None` when `images_order` is absent, and with the synced JSON when present.
- [x] **Frontend 1:** `openEdit` seeds `images` from `image_path` as `kind: 'existing'` entries, in stored order.
- [x] **Frontend 2:** `removeImage` revokes the object URL of a new photo but not the URL of an existing one.
- [x] **Frontend 3:** `canSubmit` is false when editing after every photo is removed.
- [x] **Frontend 4:** Submitting an edit posts FormData whose `images_order` interleaves kept URLs and `new:<n>` tokens to match the grid, with `new_images` in token order.
- [x] **Frontend 5:** The edit modal renders photo tiles and the add tile, and no longer renders the "not supported" hint.

# Implementation Files
- `backend/items.py` — `sync_item_images`.
- `backend/routes/admin.py` — multipart `admin_update_item`.
- `backend/schemas.py` — drop `UpdateItemSchema`.
- `backend/tests/test_items.py`, `backend/tests/test_routes_admin_orders_items.py`, `backend/tests/test_schemas.py`
- `frontend/app/components/admin/AdminItems.vue` — shared photo grid across create/edit.
- `frontend/tests/components/admin/AdminItems.test.ts`
