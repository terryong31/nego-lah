"""
CDN Assets Synchronization Script for Supabase Storage.

Uploads the brand icons that transactional emails embed by absolute URL to the
Supabase Storage CDN (both staging and production, via Infisical).

The demo walkthrough video is NOT handled here any more — SPEC-045 moved it to a
zero-egress Cloudflare R2 bucket. See `frontend/scripts/sync-media-r2.mjs`.
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

from connector import admin_supabase
from env import STORAGE_BUCKET, SUPABASE_URL


def main():
    if not SUPABASE_URL:
        print("❌ Error: SUPABASE_URL is not set.")
        sys.exit(1)

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

    print(f"🚀 Synchronizing branding CDN assets to Supabase project: {SUPABASE_URL}")
    print(f"📦 Storage bucket: '{STORAGE_BUCKET}'")

    # Verify files exist
    for asset in assets:
        p: Path = asset["local_path"]
        if not p.exists():
            print(f"❌ Missing local file: {p}")
            sys.exit(1)

    uploaded_urls = []

    for asset in assets:
        local_path: Path = asset["local_path"]
        storage_path: str = asset["storage_path"]
        content_type: str = asset["content_type"] or mimetypes.guess_type(local_path)[0] or "application/octet-stream"

        file_bytes = local_path.read_bytes()
        file_size_kb = len(file_bytes) / 1024

        print(f"\n⬆️  Uploading {storage_path} ({file_size_kb:.1f} KB)...")

        try:
            # Upload with upsert enabled and 1-year immutable cache header
            admin_supabase.storage.from_(STORAGE_BUCKET).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": content_type,
                    "cache-control": "31536000",
                    "upsert": "true",
                },
            )
            print("   ✅ Uploaded successfully.")
        except Exception as e:
            # If upload fails, check if error was just existing file with upsert behavior in SDK
            err_str = str(e)
            if "Duplicate" in err_str or "already exists" in err_str:
                print("   ℹ️  Object exists. Updating object...")
                admin_supabase.storage.from_(STORAGE_BUCKET).update(
                    path=storage_path,
                    file=file_bytes,
                    file_options={
                        "content-type": content_type,
                        "cache-control": "31536000",
                        "upsert": "true",
                    },
                )
                print("   ✅ Updated successfully.")
            else:
                print(f"   ❌ Upload failed: {e}")
                sys.exit(1)

        # Retrieve public URL
        public_url = admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        uploaded_urls.append((storage_path, public_url, content_type))

    print("\n🔍 Verifying CDN endpoints...")
    with httpx.Client(timeout=15.0) as client:
        for storage_path, url, _content_type in uploaded_urls:
            resp = client.get(url)
            is_ok = resp.status_code == 200
            status_icon = "✅" if is_ok else "❌"
            print(f"   🖼️  {storage_path}: Status {resp.status_code} {status_icon}")

            if not is_ok:
                print(f"   ⚠️ Warning: Unexpected status code {resp.status_code} for {url}")

    print("\n🎉 Branding CDN assets successfully synced to Supabase Storage!")
    for storage_path, url, _ in uploaded_urls:
        print(f"   🔗 {storage_path}: {url}")


if __name__ == "__main__":
    main()
