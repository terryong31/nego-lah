"""User media on a first-party CDN (SPEC-108, ADR-0033).

The API authorises every write; the CDN serves every read. Rows hold object
*keys* (`items/<id>/<rand>.jpeg`), never URLs, and `media_url()` builds the URL
at read time from `MEDIA_CDN_URL` — so the next host change is configuration,
not a data migration. Before SPEC-108 rows held Supabase public URLs and the
browser loaded them straight from the Supabase project, the one place it still
talked to Supabase. `media_key()` reads those legacy URLs as keys, so old rows
resolve to the same object on the CDN without waiting for a rewrite.

This is the only module that talks to object storage
(`tests/test_core_media_boundary.py` enforces it).

`MediaStore` speaks the S3 API to R2 with a small SigV4 signer over `httpx`
rather than `boto3`, which would add tens of MB of RSS to every worker on a
2 GB box for four calls. It is synchronous: callers already move storage round
trips off the event loop with `asyncio.to_thread`.
"""

import hashlib
import hmac
import re
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from defusedxml import ElementTree

from core.env import (
    MEDIA_CDN_URL,
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET,
    R2_SECRET_ACCESS_KEY,
    STORAGE_BUCKET,
    SUPABASE_URL,
)

# Every object name is unique, so every object can be cached forever.
IMMUTABLE = "public, max-age=31536000, immutable"

# Segments of letters, digits, `.`, `_`, `-`; no empty, `.` or `..` segment.
_KEY = re.compile(r"^(?!.*(?:^|/)\.{1,2}(?:/|$))[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def _legacy_prefix() -> str | None:
    if not SUPABASE_URL:
        return None
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{STORAGE_BUCKET}/"


def media_key(value: object) -> str | None:
    """The object key a stored value names, or None if it names none of ours.

    Accepts a bare key, a URL on our CDN, or a legacy public URL from this
    project's Supabase bucket. A Google avatar, another project's bucket, a
    `data:` URL or anything traversal-shaped is not ours.
    """
    if not isinstance(value, str) or not value:
        return None
    for prefix in (f"{MEDIA_CDN_URL.rstrip('/')}/", _legacy_prefix()):
        if prefix and value.startswith(prefix):
            value = value[len(prefix) :].split("?", 1)[0]
            break
    else:
        if ":" in value:
            return None
    return value if _KEY.match(value) else None


def media_url(value: str | None) -> str | None:
    """The public URL for a stored value; foreign values pass through unchanged."""
    key = media_key(value)
    if key is None:
        return value
    return f"{MEDIA_CDN_URL.rstrip('/')}/{key}"


def new_key(prefix: str, extension: str) -> str:
    """A fresh, never-reused key under `prefix` — a replaced photo is a new object."""
    return f"{prefix.strip('/')}/{uuid.uuid4().hex[:16]}.{extension}"


class MediaStoreNotConfigured(RuntimeError):
    """R2 credentials are missing. Raised rather than writing somewhere else."""


class MediaStore:
    """The four object operations the app needs, on R2's S3 API."""

    REGION = "auto"
    SERVICE = "s3"

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket
        self._client = client
        self._now = now or (lambda: datetime.now(UTC))

    # --- operations ---------------------------------------------------------

    def put(self, key: str, body: bytes, content_type: str) -> str:
        """Write one object, immutable. Returns the key."""
        self._send("PUT", key, body=body, headers={"content-type": content_type, "cache-control": IMMUTABLE})
        return key

    def delete(self, keys: Iterable[str]) -> None:
        """Remove objects. R2 answers 204 for a key that is already gone."""
        for key in keys:
            self._send("DELETE", key)

    def exists(self, key: str) -> bool:
        return self._send("HEAD", key, allow={404}).status_code == 200

    def list(self, prefix: str) -> list[str]:
        """Every key under `prefix`, across as many pages as R2 returns."""
        keys: list[str] = []
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            root = ElementTree.fromstring(self._send("GET", None, query=query).text)
            keys += [el.text for el in root.iter() if el.tag.endswith("}Key") or el.tag == "Key"]
            truncated = next((el.text for el in root.iter() if el.tag.endswith("IsTruncated")), "false")
            token = next((el.text for el in root.iter() if el.tag.endswith("NextContinuationToken")), None)
            if truncated != "true" or not token:
                return keys

    # --- transport ----------------------------------------------------------

    def _send(
        self,
        method: str,
        key: str | None,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        allow: set[int] = frozenset(),
    ) -> httpx.Response:
        if not (self._account_id and self._access_key_id and self._secret_access_key and self._bucket):
            raise MediaStoreNotConfigured("R2 credentials are not set (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, …)")
        if key is not None and media_key(key) != key:
            raise ValueError(f"Not a media key: {key!r}")

        host = f"{self._account_id}.r2.cloudflarestorage.com"
        path = "/" + quote(self._bucket) + ("/" + quote(key) if key else "")
        canonical_query = "&".join(
            f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted((query or {}).items())
        )
        signed = self._sign(method, host, path, canonical_query, body)
        url = f"https://{host}{path}" + (f"?{canonical_query}" if canonical_query else "")

        client = self._client or self._default_client()
        response = client.request(method, url, content=body or None, headers={**(headers or {}), **signed})
        if response.status_code not in allow:
            response.raise_for_status()
        return response

    def _default_client(self) -> httpx.Client:
        self._client = httpx.Client(timeout=30.0)
        return self._client

    def _sign(self, method: str, host: str, path: str, canonical_query: str, body: bytes) -> dict[str, str]:
        """AWS Signature Version 4 over host, payload hash and date."""
        now = self._now().astimezone(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()

        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                method,
                path,
                canonical_query,
                f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n",
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date}/{self.REGION}/{self.SERVICE}/aws4_request"
        string_to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
        )

        signing_key = f"AWS4{self._secret_access_key}".encode()
        for part in (date, self.REGION, self.SERVICE, "aws4_request"):
            signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

        return {
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "authorization": (
                f"AWS4-HMAC-SHA256 Credential={self._access_key_id}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }


media_store = MediaStore(
    account_id=R2_ACCOUNT_ID,
    access_key_id=R2_ACCESS_KEY_ID,
    secret_access_key=R2_SECRET_ACCESS_KEY,
    bucket=R2_BUCKET,
)
