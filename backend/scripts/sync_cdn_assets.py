"""
Brand asset sync to the media CDN (SPEC-028, SPEC-108).

Uploads the brand icons that transactional emails embed by absolute URL to the
R2 bucket behind `MEDIA_CDN_URL` (both staging and production, via Infisical).
SPEC-108 moved them off Supabase Storage with the rest of the media.

The demo walkthrough video is NOT handled here — SPEC-045 uploads it with
`frontend/scripts/sync-media-r2.mjs`.

The keys are fixed (`branding/logo.png`), so a re-upload replaces an object
that is cached `immutable`: purge the two URLs in Cloudflare after changing a
logo, or the edge keeps serving the old one.
"""

# ruff: noqa: E402
import mimetypes
import sys
from pathlib import Path

# Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx

from core.media import media_store, media_url


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    frontend_dir = repo_root / "frontend"

    logo_path = frontend_dir / "public" / "icon-512.png"
    mark_path = frontend_dir / "app" / "assets" / "icons" / "mark.svg"

    assets = [
        {
            "local_path": logo_path,
            "storage_path": "branding/logo.png",
            "content_type": "image/png",
        },
        {
            "local_path": mark_path,
            "storage_path": "branding/mark.svg",
            "content_type": "image/svg+xml",
        },
    ]

    print(f"🚀 Synchronizing branding assets to the media CDN: {media_url('')}")

    for asset in assets:
        p: Path = asset["local_path"]
        if not p.exists():
            print(f"❌ Missing local file: {p}")
            sys.exit(1)

    for asset in assets:
        local_path: Path = asset["local_path"]
        storage_path: str = asset["storage_path"]
        content_type: str = asset["content_type"] or mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        file_bytes = local_path.read_bytes()

        print(f"\n⬆️  Uploading {storage_path} ({len(file_bytes) / 1024:.1f} KB)...")
        try:
            media_store.put(storage_path, file_bytes, content_type)
            print("   ✅ Uploaded successfully.")
        except Exception as e:
            print(f"   ❌ Upload failed: {e}")
            sys.exit(1)

    print("\n🔍 Verifying CDN endpoints...")
    with httpx.Client(timeout=15.0) as client:
        for asset in assets:
            url = media_url(asset["storage_path"])
            resp = client.get(url)
            status_icon = "✅" if resp.status_code == 200 else "❌"
            print(f"   🖼️  {url}: Status {resp.status_code} {status_icon}")

    print("\n🎉 Branding assets synced.")


if __name__ == "__main__":
    main()
