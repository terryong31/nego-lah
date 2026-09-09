"""SPEC-054 — every uploaded photo is normalized before it is stored.

Two problems, one pipeline:

1. Listing photos were stored exactly as uploaded, with the extension taken from
   `img.filename` and the content type from `img.content_type` — the browser's
   word for both, which is the class of bug SPEC-044 fixed for avatars and never
   for listings. Nothing capped the pixels either, so a 12 MP phone photo was
   served at full size to every storefront visitor.
2. HEIC/HEIF — what most phones actually produce — was rejected outright by the
   magic-byte sniffer, and would have been undecodable by the vision model even
   if it had got through.

These assert the properties the pipeline holds, using images built here rather
than fixtures, so what is being decoded is visible in the test.
"""

import io

import pytest
from fastapi import HTTPException
from PIL import Image, ImageFilter

from core.images import (
    MAX_AVATAR_EDGE,
    MAX_ITEM_EDGE,
    normalize_image,
    process_upload,
)
from core.uploads import sniff_image


def photographic(size) -> Image.Image:
    """Blurred noise — the closest cheap stand-in for a real photo.

    This matters: a flat or near-flat synthetic image compresses *better* as
    lossless PNG than as JPEG, so testing format selection with one would assert
    the opposite of what real uploads do.
    """
    channels = [Image.effect_noise(size, 64).filter(ImageFilter.GaussianBlur(2)) for _ in range(3)]
    return Image.merge("RGB", channels)


def make_image(size=(64, 48), mode="RGB", fmt="PNG", color=(200, 30, 30), photo=False) -> bytes:
    buf = io.BytesIO()
    if photo:
        img = photographic(size)
        if mode == "RGBA":
            img = img.convert("RGBA")
            img.putalpha(128)
    else:
        img = Image.new(mode, size, (*color, 128) if mode == "RGBA" else color)
    img.save(buf, format=fmt)
    return buf.getvalue()


def open_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# ---------------------------------------------------------------------------
# Scenario 1 — HEIF is recognised by the sniffer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("brand", [b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"])
def test_sniff_recognises_the_heif_family(brand):
    header = b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 40
    assert sniff_image(header) == ("image/heic", "heic")


def test_sniff_rejects_a_non_image_ftyp_box():
    """`ftyp` alone is not enough — QuickTime and MP4 are ftyp containers too."""
    assert sniff_image(b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 40) is None
    assert sniff_image(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40) is None


def test_sniff_still_rejects_svg():
    """SVG is an XML document with script support — it stays out (SPEC-044)."""
    assert sniff_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") is None


# ---------------------------------------------------------------------------
# Scenario 2-3 — resizing
# ---------------------------------------------------------------------------

def test_downscales_a_large_photo_to_the_long_edge():
    data = make_image(size=(4000, 3000), fmt="JPEG")
    out, content_type, ext = normalize_image(data, max_edge=MAX_ITEM_EDGE)

    img = open_bytes(out)
    assert max(img.size) == MAX_ITEM_EDGE
    # Aspect ratio preserved (4:3 -> 2048x1536).
    assert img.size == (2048, 1536)
    assert content_type == "image/jpeg"
    assert ext == "jpg"


def test_does_not_upscale_a_small_photo():
    data = make_image(size=(100, 80), fmt="PNG")
    out, _, _ = normalize_image(data, max_edge=MAX_ITEM_EDGE)
    assert open_bytes(out).size == (100, 80)


def test_avatars_use_a_much_smaller_edge():
    data = make_image(size=(2000, 2000), fmt="JPEG")
    out, _, _ = normalize_image(data, max_edge=MAX_AVATAR_EDGE)
    assert max(open_bytes(out).size) == MAX_AVATAR_EDGE


# ---------------------------------------------------------------------------
# Scenario 4-5 — format selection
# ---------------------------------------------------------------------------

def test_transparent_images_become_webp_and_keep_their_alpha():
    data = make_image(size=(800, 600), mode="RGBA", fmt="PNG", photo=True)
    out, content_type, ext = normalize_image(data)

    assert content_type == "image/webp"
    assert ext == "webp"
    img = open_bytes(out)
    assert img.format == "WEBP"
    assert img.mode in ("RGBA", "LA", "P")
    assert img.convert("RGBA").getpixel((0, 0))[3] < 255


def test_opaque_images_become_jpeg_and_get_smaller():
    data = make_image(size=(1600, 1200), mode="RGB", fmt="PNG", photo=True)
    out, content_type, ext = normalize_image(data)

    assert (content_type, ext) == ("image/jpeg", "jpg")
    assert open_bytes(out).format == "JPEG"
    assert len(out) < len(data)


# ---------------------------------------------------------------------------
# Scenario 6 — orientation and metadata
# ---------------------------------------------------------------------------

def test_exif_orientation_is_baked_into_the_pixels_and_stripped():
    """An iPhone photo is landscape bytes plus "rotate me". Storing that verbatim
    is how a listing ends up sideways in every non-EXIF-aware renderer."""
    buf = io.BytesIO()
    img = Image.new("RGB", (400, 200), (10, 120, 200))
    exif = img.getexif()
    exif[274] = 6  # Orientation: rotate 90° CW
    img.save(buf, format="JPEG", exif=exif)

    out, _, _ = normalize_image(buf.getvalue())

    result = open_bytes(out)
    assert result.size == (200, 400)  # actually rotated, not just tagged
    assert not result.getexif().get(274)


def test_metadata_including_gps_is_dropped():
    buf = io.BytesIO()
    img = Image.new("RGB", (300, 300), (10, 120, 200))
    exif = img.getexif()
    exif[271] = "TestCamera"
    img.save(buf, format="JPEG", exif=exif)

    out, _, _ = normalize_image(buf.getvalue())
    assert b"TestCamera" not in out


# ---------------------------------------------------------------------------
# Scenario 7 — never make it worse
# ---------------------------------------------------------------------------

def test_keeps_the_original_when_re_encoding_would_be_bigger():
    """An already heavily-compressed JPEG must not be inflated by re-encoding it
    at our quality — and the returned type must still describe what we kept."""
    buf = io.BytesIO()
    photographic((300, 300)).save(buf, format="JPEG", quality=20)
    data = buf.getvalue()

    out, content_type, ext = normalize_image(data)
    assert out == data
    assert (content_type, ext) == ("image/jpeg", "jpg")


# ---------------------------------------------------------------------------
# Scenario 8 — bad input
# ---------------------------------------------------------------------------

def test_a_corrupt_payload_is_a_400_not_a_500():
    with pytest.raises(HTTPException) as exc:
        process_upload(b"\xff\xd8\xff" + b"garbage" * 100)
    assert exc.value.status_code == 400


def test_a_non_image_is_rejected_before_decoding():
    with pytest.raises(HTTPException) as exc:
        process_upload(b"<html><script>alert(1)</script></html>")
    assert exc.value.status_code == 400


def test_an_oversized_upload_is_rejected():
    data = make_image(size=(64, 48), fmt="PNG")
    with pytest.raises(HTTPException) as exc:
        process_upload(data, max_bytes=10)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Scenario 9 — HEIF round trip
# ---------------------------------------------------------------------------

def test_heif_decodes_and_comes_back_as_jpeg():
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()

    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (40, 90, 160)).save(buf, format="HEIF")
    heic = buf.getvalue()

    # It has to get past the gate first.
    assert sniff_image(heic) == ("image/heic", "heic")

    out, content_type, ext = process_upload(heic)
    assert (content_type, ext) == ("image/jpeg", "jpg")
    assert open_bytes(out).format == "JPEG"
    assert open_bytes(out).size == (1200, 900)


def test_heif_is_always_converted_even_when_that_costs_bytes():
    """No browser renders HEIC. "Smaller" is not a reason to keep it."""
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (255, 255, 255)).save(buf, format="HEIF")
    heic = buf.getvalue()

    out, content_type, _ = normalize_image(heic)
    assert content_type == "image/jpeg"
    assert out != heic


# ---------------------------------------------------------------------------
# Degradation — Pillow absent must not break uploads
# ---------------------------------------------------------------------------

def test_passes_bytes_through_when_pillow_is_unavailable(monkeypatch):
    import core.images as images

    monkeypatch.setattr(images, "Image", None)
    data = make_image(size=(4000, 3000), fmt="JPEG")

    out, content_type, ext = images.normalize_image(data)
    assert out == data
    assert (content_type, ext) == ("image/jpeg", "jpg")
