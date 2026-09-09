# ADR 0017: Server-Side Image Normalization (HEIF Ingest and Auto-Compression)

## Status
Accepted

## Context

SPEC-044 established that an upload's content type and stored extension must be
decided from its bytes, never from the request — the storage bucket is public, so a
forwarded `text/html` meant HTML *served as HTML* from the project's own origin, and
a filename with slashes escaped its prefix. That fix landed on avatars only.

Listing photos kept the old shape. `items.upload_item` and `items.sync_item_images`
took the extension from `img.filename.split(".")[-1]` and the content type from
`img.content_type`, with no size ceiling at all. Three problems compound there:

1. **The same class of bug SPEC-044 closed**, still open on the surface that
   actually serves images to the public storefront.
2. **No compression, no cap.** A 12 MP phone photo was stored and served at full
   resolution to every visitor of every listing, on a Cloudflare Pages SPA whose
   entire performance story is about not doing that.
3. **HEIC could not get in at all.** The magic-byte allowlist had no HEIF signature,
   so an iPhone user uploading an unconverted photo — the default for "Most
   Compatible: Off" — got "Unsupported image type". Worse, if it had been accepted,
   nothing downstream could decode it: no browser but Safari renders HEIC, and the
   vision model in the listing-authoring pipeline rejects it outright.

Client-side conversion is not an available answer. The frontend already downscales
for analysis via `createImageBitmap`, and that call *fails* on HEIC in Chrome and
Firefox — it falls back to the original file, silently.

## Decision

One normalization pipeline, `backend/core/images.py`, run on every image upload.

1. **Decode, then decide.** Pillow opens the bytes; the content type and extension
   come from what actually decoded. `core/uploads.py` keeps its role as the cheap
   magic-byte gate in front, now including the HEIF `ftyp` brands.

2. **Re-encode by transparency, not by input format.** Images carrying alpha become
   WebP (the only allowlisted format that keeps alpha and compresses like a photo);
   everything else becomes progressive JPEG at quality 82. Flattening alpha onto
   white would be smaller and would silently change the picture.

3. **Cap the long edge** — 2048 px for listings, 512 px for avatars — never upscale.

4. **Bake in EXIF orientation and drop all metadata.** `ImageOps.exif_transpose`
   rotates the pixels so the result is correct in renderers that ignore EXIF, and the
   re-encode drops the tags — including GPS. A second-hand listing that publishes the
   seller's home coordinates is a real problem this quietly ends.

5. **Never make it worse.** If the re-encode is larger than the input, keep the
   original bytes — *unless* the input is HEIF, which is converted regardless,
   because "smaller" is no consolation for an image no browser can display.

6. **Ceilings measure the incoming bytes** — 12 MB listings, 8 MB avatars (up from
   2 MB) — because that is what the request carried. A raw HEIC frame clears 2 MB on
   its own, so the old limit rejected the very format this pipeline exists to accept.

7. **Pillow is imported defensively.** If it is ever absent the module degrades to
   pass-through with the sniffed type, so a broken install means uncompressed
   uploads rather than a store that cannot list anything.

## Consequences

- **Listing uploads now get SPEC-044's guarantee**: the CDN serves them under a type
  derived from their bytes, and the client's filename reaches nothing.
- **Storefront payload drops sharply.** A typical 4000×3000 phone JPEG lands at
  2048 px and a fraction of the bytes; the storefront never rendered more than a few
  hundred CSS pixels of it anyway.
- **HEIC works end to end** — upload, storage, CDN delivery, and vision analysis —
  by never existing downstream of the ingest boundary.
- **Uploads cost CPU now.** Decode + resize + encode is real work on a single
  Lightsail box, so every call goes through `asyncio.to_thread`, alongside the
  storage round trip it already shared a thread hop with.
- **Re-encoding is lossy and irreversible.** The original bytes are not kept. For a
  second-hand marketplace this is the right trade — the photo is a description of an
  item, not an archival asset — but it is a real loss and worth naming.
- **Two new runtime dependencies**, `pillow` and `pillow-heif`. Both ship manylinux
  and macOS wheels with libheif bundled, so the Dockerfile needs no apt packages and
  the build stays as it was.

## Alternatives considered

- **Client-side conversion (canvas / `createImageBitmap`).** Rejected: it cannot
  decode HEIC in Chrome or Firefox, which is the case that motivated the work, and it
  leaves the server trusting the client for type and extension either way.
- **An image CDN with on-the-fly transforms.** Rejected for now: it solves delivery
  size but not the ingest-trust problem, and it adds a paid dependency to a stack
  whose media story (ADR-0010) is deliberately zero-egress.
- **Storing the original alongside the normalized copy.** Rejected: it doubles
  storage for an asset nothing reads, on the one surface where the public URL is the
  product.
