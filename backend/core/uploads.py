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
            detail="Unsupported image type. Upload a JPEG, PNG, GIF or WebP.",
        )

    return sniffed
