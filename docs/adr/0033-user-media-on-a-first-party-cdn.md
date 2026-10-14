# ADR-0033: User media is served from R2 on our own domain and stored as keys

- Status: Accepted
- Date: 2026-10-14
- Relates to: SPEC-108; completes ADR-0010's follow-on; closes the read-side gap in ADR-0028

## Context

ADR-0028 made FastAPI the BFF: the SPA makes no Supabase calls. That held for API traffic and
uploads, but every item photo and avatar was still an `<img>` pointed at the Supabase project's
storage host, because rows stored `get_public_url()` output. `img-src https:` let it through, so
nothing flagged it; SPEC-107 surfaced it only when a service-worker rule re-issued those loads as
`fetch()` under `connect-src`.

Those images must stay publicly fetchable: link-preview bots read `og:image`, the LLM provider
fetches photos for vision, and mail clients load the logo — none of them carry our cookie.

## Considered options

1. **Proxy bytes through FastAPI** (`api.negolah.my/media/…`) — strictest reading of "everything
   through the API", but every image byte crosses a 2 GB Lightsail worker and still pays Supabase
   egress; the API record is not yet edge-cached. The common anti-pattern for public media.
2. **A Cloudflare Worker fronting Supabase Storage** — hides the vendor host without moving
   anything; Supabase egress is still billed and a Worker joins the things to maintain.
3. **R2 behind `media.negolah.my`** — the bucket and domain already exist (ADR-0010); zero egress;
   served from the same edge as the SPA. Chosen.

## Decision

- Uploads stay server-side (re-encoded per ADR-0017) and go to R2 through `core/media.py`, the only
  module that may talk to object storage.
- Rows store object keys. `media_url()` builds the URL at read time from `MEDIA_CDN_URL`, so the
  next host change is configuration, not a data migration.
- Every object name is unique and written `immutable`; a replaced photo is a new key.
- Legacy Supabase URLs are read as keys, so the deploy does not wait on the row rewrite.
- After prod is verified, `img-src` and `media-src` are narrowed to first-party hosts plus the
  Google avatar host, making the BFF rule something the browser enforces.

## Consequences

- The browser no longer contacts Supabase for anything. Media egress costs nothing and cannot
  throttle auth or the database (ADR-0010's blast-radius argument, now for user media).
- R2 write credentials join Infisical, and the backend carries a small SigV4 signer instead of
  `boto3`. A signer bug fails uploads loudly; it is pinned by a recorded test vector.
- `media.negolah.my` is a subdomain, so `.negolah.my` cookies are sent to it. Acceptable because it
  serves only bytes we re-encoded to raster images under `nosniff`; a separate registrable domain
  for user content is the stronger option if uploads ever stop being re-encoded.
- Two stores exist until the copy is verified; the Supabase bucket is retired in phase 2.
