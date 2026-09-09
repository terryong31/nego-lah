"""Normalization for user-supplied images (SPEC-054).

`core/uploads.py` decides whether a payload is an image *at all* — a magic-byte
gate, deliberately not a decoder. This module is the decoder, and it runs on
everything that gets past that gate.

Three things it fixes, all of which were the browser's word before:

  * The stored extension and content type came from `filename` / `content_type`.
    They now come from what actually decoded, so a listing photo can no longer
    be stored under a type it isn't. (Avatars got this in SPEC-044; listings
    never did.)
  * Nothing capped the pixels, so a 12 MP phone photo was served at full size to
    every storefront visitor. The long edge is capped and the file re-encoded.
  * HEIC — what most phones actually produce — could not be decoded by anything
    downstream, browser or vision model. It is decoded here and converted.

A side effect worth naming: re-encoding drops EXIF, and EXIF on a phone photo
carries GPS. A second-hand listing that publishes the seller's home coordinates
is a real problem, and this quietly ends it.

Pillow is imported defensively. If it is ever missing the module degrades to
pass-through — an uncompressed upload is a worse outcome than a failed one, but
not by nearly as much as a store that cannot list anything.
"""

import io

from fastapi import HTTPException

from core.uploads import MAX_ITEM_IMAGE_BYTES, validate_image_upload
from logger import logger

try:
    from PIL import Image, ImageOps
except Exception as e:  # pragma: no cover - only on a broken install
    Image = None
    ImageOps = None
    logger.warning(f"⚠️ Pillow unavailable; image normalization disabled: {e}")

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception as e:  # pragma: no cover - only on a broken install
    logger.warning(f"⚠️ pillow-heif unavailable; HEIC uploads cannot be converted: {e}")

# Long-edge ceilings. 2048 is comfortably above what the storefront ever renders
# (the largest card is a few hundred CSS pixels, doubled for retina) while still
# leaving a listing photo worth zooming into.
MAX_ITEM_EDGE = 2048
MAX_AVATAR_EDGE = 512

JPEG_QUALITY = 82
WEBP_QUALITY = 82

# Formats that must be re-encoded no matter what the byte count says, because
# nothing downstream can render them: no browser ships a HEIC decoder outside
# Safari, and the vision model rejects them outright.
_ALWAYS_CONVERT = frozenset({"HEIF", "HEIC", "AVIF"})


def _has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def normalize_image(
    data: bytes,
    *,
    max_edge: int = MAX_ITEM_EDGE,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str, str]:
    """Return `(bytes, content_type, extension)` for the image to actually store.

    Downscales to `max_edge`, applies EXIF orientation, strips metadata, and
    re-encodes: WebP when the image carries transparency, progressive JPEG
    otherwise. Never upscales.

    Raises 400 if the bytes do not decode. Callers must use all three returned
    values — deciding the content type from the decode is the point.
    """
    if Image is None:
        # Pass-through: fall back to the sniffer's opinion so callers still get
        # a usable content type rather than the client's claim.
        from core.uploads import sniff_image
        sniffed = sniff_image(data)
        if sniffed is None:
            raise HTTPException(status_code=400, detail="Unsupported image type.")
        return data, sniffed[0], sniffed[1]

    try:
        with Image.open(io.BytesIO(data)) as src:
            source_format = (src.format or "").upper()
            # `exif_transpose` reads the orientation tag and rotates the pixels,
            # which is what makes the result correct in renderers that ignore
            # EXIF — and, since we then drop EXIF, in the ones that don't.
            img = ImageOps.exif_transpose(src)
            img.load()

            longest = max(img.size)
            if longest > max_edge:
                scale = max_edge / longest
                img = img.resize(
                    (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                    Image.LANCZOS,
                )

            buf = io.BytesIO()
            if _has_alpha(img):
                # WebP is the only allowlisted format that keeps alpha and still
                # compresses like a photo. Flattening onto white instead would
                # be smaller, but it would silently change the picture.
                img.convert("RGBA").save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
                content_type, ext, out_format = "image/webp", "webp", "WEBP"
            else:
                img.convert("RGB").save(
                    buf, format="JPEG", quality=quality, optimize=True, progressive=True
                )
                content_type, ext, out_format = "image/jpeg", "jpg", "JPEG"
    except HTTPException:
        raise
    except Exception as e:
        # A payload that passed the magic-byte gate but will not decode is a
        # bad *request*, not a server fault — 400, and never a stack trace.
        logger.warning(f"⚠️ Rejected an undecodable image upload: {e}")
        raise HTTPException(status_code=400, detail="That image could not be read.") from e

    encoded = buf.getvalue()

    # Re-encoding a small, already-optimal file can make it bigger. Keeping the
    # original is only safe when the original is something a browser can show —
    # a HEIC is converted even at a size cost, because the alternative is a
    # broken image everywhere but Safari.
    if len(encoded) >= len(data) and source_format not in _ALWAYS_CONVERT:
        from core.uploads import sniff_image
        sniffed = sniff_image(data)
        if sniffed is not None:
            return data, sniffed[0], sniffed[1]

    logger.info(
        f"🖼️ Normalized image: {len(data)} -> {len(encoded)} bytes "
        f"({source_format or 'unknown'} -> {out_format})"
    )
    return encoded, content_type, ext


def process_upload(
    data: bytes,
    *,
    max_edge: int = MAX_ITEM_EDGE,
    max_bytes: int = MAX_ITEM_IMAGE_BYTES,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str, str]:
    """Validate then normalize one upload — the single entry point for routes.

    `max_bytes` is measured on the INCOMING bytes, before compression, since
    that is what the request actually carried.
    """
    validate_image_upload(data, max_bytes=max_bytes)
    return normalize_image(data, max_edge=max_edge, quality=quality)
