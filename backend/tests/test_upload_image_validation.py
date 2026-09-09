"""Uploads are what the bytes say they are, not what the browser claims.
(SPEC-044 C)

Both avatar routes used to pass the request's `content-type` straight through
to Supabase Storage and build the stored object's name from the request's
`filename`. The bucket is public, so that combination is:

- **Stored XSS / arbitrary file hosting.** Upload HTML, declare it
  `text/html`, and it is served as HTML from the project's own storage origin.
  A phishing page on your domain, hosted by you, linked from your CDN.
- **Path traversal.** The extension came from `filename.rsplit(".", 1)[-1]`
  with no sanitising, so a filename containing slashes escaped the
  `avatars/<user_id>/` prefix the layout depends on.

The fix is to decide both facts server-side by sniffing magic bytes, and to
allowlist raster formats only. SVG is excluded deliberately: it is an image by
convention and an XML document with `<script>` support in practice, which is
the one "image" type that survives being served with an image content type.

These tests assert on what reaches storage, because that is the only thing
that determines how the file is later served.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.uploads import MAX_AVATAR_IMAGE_BYTES, sniff_image, validate_image_upload
from routes.admin import users as admin_users


def _encode(fmt: str, size=(8, 8), mode="RGB", color=(200, 30, 30)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


def _encode_heic(size=(8, 8)) -> bytes:
    import io

    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 140, 90)).save(buf, format="HEIF")
    return buf.getvalue()


# Magic bytes are all the *sniffer* reads, but since SPEC-054 the routes also
# DECODE what gets past it, so these have to be whole encoded images.
# Deliberately tiny and flat: re-encoding one costs more bytes than it saves, so
# the pipeline keeps the original and these tests still describe the format that
# was actually posted rather than the pipeline's preferred output.
PNG = _encode("PNG")
JPEG = _encode("JPEG")
GIF = _encode("GIF")
WEBP = _encode("WEBP")

# A HEIC frame — the format most phone photos actually arrive in, and the one
# the sniffer used to reject outright.
HEIC = _encode_heic()

HTML = b"<html><script>alert(document.cookie)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


# --- the sniffer -------------------------------------------------------------

@pytest.mark.parametrize(
    "data,expected",
    [
        (PNG, ("image/png", "png")),
        (JPEG, ("image/jpeg", "jpg")),
        (GIF, ("image/gif", "gif")),
        (WEBP, ("image/webp", "webp")),
    ],
    ids=["png", "jpeg", "gif", "webp"],
)
def test_supported_formats_are_recognised(data, expected):
    assert sniff_image(data) == expected


@pytest.mark.parametrize(
    "data",
    [HTML, SVG, b"", b"\x00" * 32, b"%PDF-1.4", b"PK\x03\x04", b"GIF"],
    ids=["html", "svg", "empty", "zeros", "pdf", "zip", "truncated-gif"],
)
def test_everything_else_is_rejected(data):
    assert sniff_image(data) is None


def test_webp_needs_more_than_the_riff_container():
    """RIFF is a generic container — WAV and AVI share it. Matching on RIFF
    alone would let a non-image through under an `image/webp` label."""
    assert sniff_image(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 64) is None


# --- the validator -----------------------------------------------------------

def test_validator_returns_the_sniffed_type_and_extension():
    assert validate_image_upload(PNG) == ("image/png", "png")


def test_validator_rejects_a_disguised_html_document():
    """The actual attack: HTML bytes, an image filename, an image
    content-type. Only the bytes are consulted."""
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(HTML)

    assert exc.value.status_code == 400


def test_validator_rejects_svg():
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(SVG)

    assert exc.value.status_code == 400


def test_validator_enforces_the_size_ceiling():
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(PNG + b"\x00" * (2 * 1024 * 1024))

    assert exc.value.status_code == 400
    assert "too large" in exc.value.detail.lower()


def test_validator_allows_exactly_the_ceiling():
    data = PNG + b"\x00" * (2 * 1024 * 1024 - len(PNG))
    assert len(data) == 2 * 1024 * 1024
    assert validate_image_upload(data) == ("image/png", "png")


def test_size_is_checked_before_type():
    """A 40MB file should be refused on sight, not sniffed first — the point of
    the ceiling is to not think about oversized input."""
    with pytest.raises(HTTPException) as exc:
        validate_image_upload(HTML + b"\x00" * (40 * 1024 * 1024))

    assert "too large" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# PUT /user/{user_id}/profile
# ---------------------------------------------------------------------------

def _existing_user(metadata=None):
    result = MagicMock()
    result.user.user_metadata = metadata if metadata is not None else {}
    return result


def _user_admin_client():
    fake = MagicMock()
    fake.auth.admin.get_user_by_id.return_value = _existing_user()
    fake.storage.from_.return_value.get_public_url.return_value = "https://cdn/x"
    return fake


async def test_profile_avatar_rejects_html_wearing_an_image_filename(
    client, auth_user, patch_supabase
):
    """The upload the finding is about: HTML bytes under `photo.png` and
    `image/png`. Nothing may reach the public bucket."""
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("photo.png", HTML, "image/png")},
    )

    assert resp.status_code == 400
    fake_admin.storage.from_.return_value.upload.assert_not_called()
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_profile_avatar_rejects_svg(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("photo.svg", SVG, "image/svg+xml")},
    )

    assert resp.status_code == 400
    fake_admin.storage.from_.return_value.upload.assert_not_called()


async def test_profile_avatar_stores_the_sniffed_type_not_the_declared_one(
    client, auth_user, patch_supabase
):
    """A real PNG declared as `text/html` is still stored as `image/png`. The
    declared value is never consulted, so it can't be used to pick how the
    file will later be served."""
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("photo.png", PNG, "text/html")},
    )

    assert resp.status_code == 200
    upload_args = fake_admin.storage.from_.return_value.upload.call_args[0]
    assert upload_args[2]["content-type"] == "image/png"


async def test_profile_avatar_accepts_a_heic_photo_and_stores_it_as_jpeg(
    client, auth_user, patch_supabase
):
    """SPEC-054: HEIC is what an iPhone actually produces. It used to be
    rejected by the sniffer, and would have been unrenderable by every browser
    but Safari if it had got through — so it is accepted and converted."""
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("IMG_0042.HEIC", HEIC, "image/heic")},
    )

    assert resp.status_code == 200
    upload_args = fake_admin.storage.from_.return_value.upload.call_args[0]
    assert upload_args[0].endswith(".jpg")
    assert upload_args[2]["content-type"] == "image/jpeg"
    # Converted, not passed through: no browser renders the original.
    assert upload_args[1] != HEIC


async def test_profile_avatar_extension_comes_from_the_bytes(
    client, auth_user, patch_supabase
):
    """A JPEG named `.php` is stored as `.jpg`. Storage serves by the
    content-type we set, but the extension is what a human reads in the URL and
    what a misconfigured proxy might key off."""
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("shell.php", JPEG, "image/jpeg")},
    )

    assert resp.status_code == 200
    file_path = fake_admin.storage.from_.return_value.upload.call_args[0][0]
    assert file_path.endswith(".jpg")
    assert "php" not in file_path


async def test_profile_avatar_filename_cannot_escape_the_user_prefix(
    client, auth_user, patch_supabase
):
    """`avatars/<user_id>/` is the layout every other part of the system
    assumes. A filename with slashes in it used to walk straight out of it."""
    auth_user("user-1")
    fake_admin = _user_admin_client()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("x.png/../../../public/index.html", PNG, "image/png")},
    )

    assert resp.status_code == 200
    file_path = fake_admin.storage.from_.return_value.upload.call_args[0][0]
    assert file_path.startswith("avatars/user-1/")
    assert ".." not in file_path
    assert file_path.count("/") == 2


# ---------------------------------------------------------------------------
# POST /admin/users/{user_id}/avatar
# ---------------------------------------------------------------------------

async def test_admin_avatar_rejects_non_images(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    """The admin route had no validation and no size limit at all. Being
    behind an admin session makes it lower-risk, not correct — it writes to
    the same public bucket."""
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("photo.png", HTML, "image/png")},
    )

    assert resp.status_code == 400
    fake_supabase.storage.from_.return_value.upload.assert_not_called()


async def test_admin_avatar_does_not_fall_back_to_base64_for_a_rejected_file(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    """The storage-failure fallback inlines the bytes into a `data:` URL built
    from the declared content type. Validation has to happen outside that
    try/except, or a rejected file comes back as a `data:text/html` URL stored
    on the profile."""
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.storage.from_.return_value.upload.side_effect = Exception("down")

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("evil.html", HTML, "text/html")},
    )

    assert resp.status_code == 400
    assert "base64" not in resp.text


async def test_admin_avatar_base64_fallback_uses_the_sniffed_type(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.storage.from_.return_value.upload.side_effect = Exception("down")

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("photo.png", GIF, "text/html")},
    )

    assert resp.status_code == 200
    assert resp.json()["avatar_url"].startswith("data:image/gif;base64,")


async def test_admin_avatar_enforces_a_size_ceiling(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("big.png", PNG + b"\x00" * MAX_AVATAR_IMAGE_BYTES, "image/png")},
    )

    assert resp.status_code == 400
    fake_supabase.storage.from_.return_value.upload.assert_not_called()


async def test_admin_avatar_path_is_built_only_from_server_chosen_values(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    """This route interpolated the raw filename into the storage key."""
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn/x"

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("../../etc/passwd.png", PNG, "image/png")},
    )

    assert resp.status_code == 200
    file_path = fake_supabase.storage.from_.return_value.upload.call_args[0][0]
    assert file_path.startswith("avatars/target-user_")
    assert file_path.endswith(".png")
    assert ".." not in file_path
    assert "passwd" not in file_path
