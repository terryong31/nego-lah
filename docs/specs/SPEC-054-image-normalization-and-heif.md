---
id: SPEC-054
title: Server-Side Image Normalization - Auto-Compression and HEIF Ingest
status: complete
priority: medium
created: 2026-09-09
tags: [uploads, media, performance, security]
assigned: agent
---

# Context & Objectives

Listing photos are stored exactly as uploaded. `items.upload_item` /
`items.sync_item_images` take the extension from `img.filename` and the content type
from `img.content_type` — the browser's word for both, which is the class of bug
SPEC-044 fixed for avatars but never for listings. Nothing caps the size either, so a
12 MP phone photo is served to every storefront visitor at full resolution.

And the one format most phone photos actually arrive in — HEIC/HEIF — is rejected
outright: `sniff_image` has no signature for it, so an iPhone user picking "Original"
gets "Unsupported image type", while the vision-analysis path would forward bytes
Gemini cannot decode.

Normalize every upload in one place: decode it, honour its EXIF orientation, cap its
long edge, re-encode it compressed, and let the *decoder* decide the content type.

# Acceptance Criteria

- [x] `sniff_image` recognises the HEIF family (`ftyp` brands `heic`, `heix`, `heim`,
      `heis`, `hevc`, `hevx`, `hevm`, `hevs`, `heif`, `mif1`, `msf1`) and reports
      `image/heic`. SVG stays rejected.
- [x] `normalize_image(data, max_edge, quality)` returns `(bytes, content_type, ext)`:
  - HEIF/HEIC decodes and is **always** re-encoded (no browser serves HEIC).
  - Images with an alpha channel encode to WebP; everything else to progressive JPEG.
  - The long edge is capped (listings 2048 px, avatars 512 px); smaller images are
    not upscaled.
  - EXIF orientation is applied to the pixels, and all metadata — GPS included — is
    dropped by the re-encode.
  - A result that would be **larger** than the input keeps the original bytes, unless
    the input was HEIF (which must be converted regardless).
- [x] A corrupt or undecodable payload raises HTTP 400, never a 500.
- [x] Listing uploads (`upload_item`, `sync_item_images`) store the normalized bytes
      under the sniffed extension and content type, never the client's.
- [x] Avatar uploads (user + admin) are normalized after validation.
- [x] The vision-analysis path (`_encode_images`) normalizes before base64, so a HEIC
      pick from an iPhone analyses correctly.
- [x] Upload ceilings acknowledge the pre-compression size: listings 12 MB per photo,
      avatars 8 MB (raw HEIC from a modern phone exceeds the old 2 MB cap).
- [x] Pillow is an optional import: with it absent the module passes bytes through
      unchanged rather than breaking uploads.

# Technical Design & Contracts

`backend/core/images.py`

```python
MAX_ITEM_EDGE   = 2048
MAX_AVATAR_EDGE = 512
JPEG_QUALITY    = 82
WEBP_QUALITY    = 82

def normalize_image(data: bytes, *, max_edge: int = MAX_ITEM_EDGE,
                    quality: int = JPEG_QUALITY) -> tuple[bytes, str, str]
def process_upload(data: bytes, *, max_edge=..., max_bytes=...) -> tuple[bytes, str, str]
```

`process_upload` = `validate_image_upload` (size + magic bytes) then
`normalize_image`. `pillow-heif` is registered once at import; both it and Pillow are
guarded so the module degrades to pass-through instead of failing closed.

Dependencies: `pillow>=11.4.0`, `pillow-heif>=1.1.0` (both ship manylinux/macOS
wheels — no apt packages, so the Dockerfile is untouched).

Frontend: file inputs accept `image/*,.heic,.heif`, and the drop handler admits a file
whose `type` is blank but whose name carries a known image extension — Chrome reports
no MIME type for `.heic`, so a dropped iPhone photo was being silently discarded.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1 (HEIF sniff):** an `ftyp heic` header sniffs as `("image/heic", "heic")`; `ftypqt  ` does not.
- [x] **Scenario 2 (downscale):** a 4000x3000 JPEG normalizes to a long edge of 2048, same aspect ratio.
- [x] **Scenario 3 (no upscale):** a 100x80 PNG keeps its dimensions.
- [x] **Scenario 4 (alpha):** an RGBA PNG normalizes to `image/webp` with alpha intact.
- [x] **Scenario 5 (opaque):** an RGB PNG normalizes to `image/jpeg`, smaller than the input.
- [x] **Scenario 6 (EXIF orientation):** an orientation-6 JPEG comes back rotated, with no EXIF block.
- [x] **Scenario 7 (already small):** a tiny JPEG that cannot be beaten keeps its original bytes.
- [x] **Scenario 8 (corrupt):** `process_upload(b"\xff\xd8\xff" + junk)` raises HTTPException 400.
- [x] **Scenario 9 (HEIF round trip):** a real HEIC payload decodes and comes back as JPEG.
- [x] **Scenario 10 (listing storage):** `upload_item` uploads the normalized bytes with
      the sniffed content type, ignoring a lying `content_type`/`filename`.

# Implementation Files

- `backend/core/images.py` - Normalization pipeline
- `backend/core/uploads.py` - HEIF signature, per-surface size ceilings
- `backend/items.py` - Normalize listing photos on create and edit
- `backend/routes/user.py`, `backend/routes/admin/users.py` - Normalize avatars
- `backend/routes/admin/listings.py` - Normalize before vision analysis
- `backend/pyproject.toml` - `pillow`, `pillow-heif`
- `frontend/app/components/admin/AdminItemFormModal.vue`, `frontend/app/pages/profile.vue` - accept HEIC
- `frontend/app/composables/useItemImages.ts` - Admit typeless HEIC drops
- `backend/tests/test_core_images.py`, `backend/tests/test_upload_image_validation.py` - Scenarios 1-10
- `docs/adr/0017-server-side-image-normalization.md` - Architecture decision record
