"""SPEC-108 — `resolve_avatar_url` serves an uploaded avatar from the CDN."""

from domains.identity.profiles import resolve_avatar_url

CDN = "https://media.example.test"
GOOGLE = "https://lh3.googleusercontent.com/a/photo"


def test_an_uploaded_avatar_key_resolves_to_the_cdn():
    assert (
        resolve_avatar_url({"custom_avatar_url": "avatars/u/a.png", "avatar_url": GOOGLE}) == f"{CDN}/avatars/u/a.png"
    )


def test_a_provider_photo_passes_through():
    assert resolve_avatar_url({"avatar_url": GOOGLE}) == GOOGLE


def test_the_legacy_profile_row_resolves_too():
    legacy = "https://test-project.supabase.co/storage/v1/object/public/test-images/avatars/u_1.png"
    assert resolve_avatar_url({}, {"avatar_url": legacy}) == f"{CDN}/avatars/u_1.png"
    assert resolve_avatar_url({}, {"avatar_url": "data:image/png;base64,AAAA"}) == "data:image/png;base64,AAAA"


def test_no_avatar_is_none():
    assert resolve_avatar_url({}) is None
