"""SPEC-108 — user media on a first-party CDN, stored as keys.

`media_key` / `media_url` decide what every stored image value means, so they
are tested over every shape a row can hold today: a bare key, our CDN URL, a
legacy Supabase URL (with the trailing `?` Supabase appends), and the foreign
values that must pass through untouched.

`MediaStore` talks the S3 API to R2 with a hand-rolled SigV4 signer. Its
signature is pinned to a vector botocore produced for the same inputs, so a
signer regression fails here rather than as a 403 on the first prod upload.
"""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from core import media
from core.media import MediaStore, MediaStoreNotConfigured, media_key, media_url

CDN = "https://media.example.test"
LEGACY = "https://test-project.supabase.co/storage/v1/object/public/test-images"


@pytest.fixture(autouse=True)
def _cdn(monkeypatch):
    monkeypatch.setattr(media, "MEDIA_CDN_URL", CDN)


# ---------------------------------------------------------------------------
# media_key / media_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("items/abc/1a2b3c4d.jpeg", "items/abc/1a2b3c4d.jpeg"),
        (f"{CDN}/items/abc/0.jpeg", "items/abc/0.jpeg"),
        (f"{LEGACY}/items/abc/0.jpeg", "items/abc/0.jpeg"),
        # supabase-py's get_public_url appends a bare `?`.
        (f"{LEGACY}/avatars/u-1/x.png?", "avatars/u-1/x.png"),
        (f"{LEGACY}/branding/logo.png?width=400", "branding/logo.png"),
    ],
)
def test_media_key_reads_every_form_a_row_can_hold(value, key):
    assert media_key(value) == key


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        42,
        "https://lh3.googleusercontent.com/a/photo.jpg",
        # Another project's bucket, or another bucket in ours, is not our media.
        "https://other-project.supabase.co/storage/v1/object/public/test-images/items/a/0.jpeg",
        "https://test-project.supabase.co/storage/v1/object/public/other-bucket/a.png",
        "data:image/png;base64,AAAA",
        "/items/a/0.jpeg",
        "items/../../etc/passwd",
        f"{CDN}/../secret",
        "items/a b/0.jpeg",
    ],
)
def test_media_key_rejects_anything_that_is_not_one_of_our_objects(value):
    assert media_key(value) is None


def test_media_url_resolves_keys_and_legacy_urls_to_the_cdn():
    assert media_url("items/abc/0.jpeg") == f"{CDN}/items/abc/0.jpeg"
    assert media_url(f"{LEGACY}/items/abc/0.jpeg?") == f"{CDN}/items/abc/0.jpeg"
    assert media_url(f"{CDN}/items/abc/0.jpeg") == f"{CDN}/items/abc/0.jpeg"


@pytest.mark.parametrize(
    "value",
    [None, "", "https://lh3.googleusercontent.com/a/photo.jpg", "data:image/png;base64,AAAA"],
)
def test_media_url_passes_foreign_values_through(value):
    assert media_url(value) == value


def test_media_url_tolerates_a_trailing_slash_on_the_cdn_setting(monkeypatch):
    monkeypatch.setattr(media, "MEDIA_CDN_URL", f"{CDN}/")
    assert media_url("items/a/0.jpeg") == f"{CDN}/items/a/0.jpeg"
    assert media_key(f"{CDN}/items/a/0.jpeg") == "items/a/0.jpeg"


def test_new_key_is_unique_and_scoped():
    first = media.new_key("items/item-1", "jpeg")
    second = media.new_key("items/item-1", "jpeg")
    assert first != second
    assert first.startswith("items/item-1/") and first.endswith(".jpeg")
    assert media_key(first) == first


# ---------------------------------------------------------------------------
# MediaStore (S3 API on R2)
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)

# Produced by botocore's S3SigV4Auth (region "auto") for the same credentials,
# clock, URL and body, with `get_current_datetime` frozen at FIXED_NOW.
BOTOCORE_PUT_SIGNATURE = "a2a02880c5dfb197d043b862f95c3173768a7088328859ce4cbcbfc4000af417"
BOTOCORE_LIST_SIGNATURE = "58a59f66aa817e22092c32ab429c945a28fb1f44a6e5900e392c59d733c55324"


def _store(handler):
    return MediaStore(
        account_id="acct",
        access_key_id="AKIDEXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        bucket="media-bucket",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: FIXED_NOW,
    )


def test_put_signs_the_request_exactly_as_botocore_does():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    _store(handler).put("items/abc/1a2b.jpeg", b"jpeg-bytes", "image/jpeg")

    (request,) = seen
    assert request.method == "PUT"
    assert str(request.url) == "https://acct.r2.cloudflarestorage.com/media-bucket/items/abc/1a2b.jpeg"
    assert request.content == b"jpeg-bytes"
    assert request.headers["content-type"] == "image/jpeg"
    assert request.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert request.headers["x-amz-date"] == "20261014T120000Z"
    assert request.headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261014/auto/s3/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
        f"Signature={BOTOCORE_PUT_SIGNATURE}"
    )


def test_list_signs_its_query_string_exactly_as_botocore_does():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text="<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>")

    assert _store(handler).list("avatars/u-1/") == []
    assert str(seen[0].url) == "https://acct.r2.cloudflarestorage.com/media-bucket?list-type=2&prefix=avatars%2Fu-1%2F"
    assert seen[0].headers["authorization"].endswith(f"Signature={BOTOCORE_LIST_SIGNATURE}")


def test_put_raises_when_r2_refuses():
    store = _store(lambda request: httpx.Response(403, text="SignatureDoesNotMatch"))
    with pytest.raises(httpx.HTTPStatusError):
        store.put("items/a/0.jpeg", b"x", "image/jpeg")


def test_put_refuses_a_key_that_is_not_one_of_ours():
    store = _store(lambda request: httpx.Response(200))
    with pytest.raises(ValueError):
        store.put("../escape.png", b"x", "image/png")


def test_list_pages_through_every_continuation_token():
    pages = {
        None: ("<Key>avatars/u-1/a.png</Key><Key>avatars/u-1/b.png</Key>", "tok-2"),
        "tok-2": ("<Key>avatars/u-1/c.png</Key>", None),
    }
    queries = []

    def handler(request):
        query = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        queries.append(query)
        body, token = pages[query.get("continuation-token")]
        truncated = "true" if token else "false"
        next_token = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{truncated}</IsTruncated>{next_token}"
            + body.replace("<Key>", "<Contents><Key>").replace("</Key>", "</Key></Contents>")
            + "</ListBucketResult>"
        )
        return httpx.Response(200, text=xml)

    keys = _store(handler).list("avatars/u-1/")

    assert keys == ["avatars/u-1/a.png", "avatars/u-1/b.png", "avatars/u-1/c.png"]
    assert all(q["list-type"] == "2" and q["prefix"] == "avatars/u-1/" for q in queries)


def test_delete_removes_each_key():
    deleted = []

    def handler(request):
        deleted.append((request.method, request.url.path))
        return httpx.Response(204)

    _store(handler).delete(["items/a/0.jpeg", "items/a/1.jpeg"])

    assert deleted == [
        ("DELETE", "/media-bucket/items/a/0.jpeg"),
        ("DELETE", "/media-bucket/items/a/1.jpeg"),
    ]


def test_exists_reads_head():
    store = _store(lambda request: httpx.Response(200 if request.url.path.endswith("here.png") else 404))
    assert store.exists("items/a/here.png") is True
    assert store.exists("items/a/gone.png") is False


def test_an_unconfigured_store_fails_loudly_instead_of_writing_somewhere_else():
    store = MediaStore(account_id="", access_key_id="", secret_access_key="", bucket="b")
    with pytest.raises(MediaStoreNotConfigured):
        store.put("items/a/0.jpeg", b"x", "image/jpeg")
