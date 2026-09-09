"""Validation for user-supplied image uploads (SPEC-044 C).

Both avatar routes used to take the browser's word for what had been uploaded:
the request's `content-type` was forwarded to Supabase Storage verbatim, and
the stored object's extension came from the request's `filename`. The bucket is
public, so declaring `text/html` got HTML stored and *served as HTML* from the
project's own storage origin, and a filename containing slashes escaped the
`avatars/<user_id>/` prefix.

Both facts are decided here instead, from the bytes. The allowlist is raster
formats only — SVG is excluded deliberately, being the one "image" that is
really an XML document with `<script>` support, and so the one that stays
dangerous even when served under an image content type.

This is a magic-byte check, not a decoder: it does not prove the file is a
*valid* image, only that it is not something else wearing an image's name.
That is the property that matters here, because the content type is what
decides how a browser will later treat the response.
"""

from fastapi import HTTPException

MAX_IMAGE_BYTES = 2 * 1024 * 1024

# SPEC-054 — the ceilings are *pre-compression*, because that is what actually
# arrives. A raw HEIC frame off a modern phone clears 2 MB on its own, so the
# old avatar limit rejected the format the pipeline now exists to accept. What
# gets stored is the normalized output, which is a fraction of these.
MAX_ITEM_IMAGE_BYTES = 12 * 1024 * 1024
MAX_AVATAR_IMAGE_BYTES = 8 * 1024 * 1024

# ISO base-media brands that mean "this box holds a still image", as opposed to
# the video the same container is more famous for. `ftyp` alone is not a
# signature: MP4 and QuickTime carry it too, so the brand at offset 8 is what
# separates an iPhone photo from an iPhone video.
_HEIF_BRANDS = frozenset({
    b"heic", b"heix", b"heim", b"heis",   # HEVC still image
    b"hevc", b"hevx", b"hevm", b"hevs",   # HEVC image sequence
    b"heif", b"mif1", b"msf1",            # generic HEIF image / image sequence
})

_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)


def sniff_image(data: bytes) -> tuple[str, str] | None:
    """Return `(content_type, extension)` for a supported image, else None."""
    for magic, content_type, extension in _SIGNATURES:
        if data.startswith(magic):
            return content_type, extension

    # WebP is a RIFF container, and RIFF alone is not enough to go on — WAV and
    # AVI are RIFF too, so matching the prefix would label arbitrary media as
    # `image/webp`. The format tag at offset 8 is what makes it an image.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"

    # HEIF/HEIC (SPEC-054) — same shape of check, one box further in: an ISO
    # base-media file starts with a length-prefixed `ftyp` box whose brand says
    # what the container actually holds.
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "image/heic", "heic"

    return None


def validate_image_upload(
    data: bytes, *, max_bytes: int = MAX_IMAGE_BYTES
) -> tuple[str, str]:
    """Return the `(content_type, extension)` to store this upload under.

    Raises 400 if it is too large or is not a supported image. Callers must use
    the returned values rather than anything from the request — that is the
    whole point of the function.
    """
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large (max {max_bytes // (1024 * 1024)}MB)",
        )

    sniffed = sniff_image(data)
    if sniffed is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image type. Upload a JPEG, PNG, GIF, WebP or HEIC.",
        )

    return sniffed
