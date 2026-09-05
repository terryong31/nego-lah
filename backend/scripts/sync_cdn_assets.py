"""
CDN Assets Synchronization Script for Supabase Storage.
Uploads brand icons and FastStart-optimized demo video to the Supabase Storage CDN
(supports both staging and production environments via Infisical).
"""

# ruff: noqa: E402
import mimetypes
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Add backend root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx

from connector import admin_supabase
from env import STORAGE_BUCKET, SUPABASE_URL


def check_faststart(video_path: Path) -> bool:
    """Check if the first atom after ftyp is moov."""
    with open(video_path, "rb") as f:
        # First atom
        header = f.read(8)
        if len(header) < 8:
            return False

        size1, _ = struct.unpack(">I4s", header)
        f.seek(size1)
        # Second atom
        header2 = f.read(8)
        if len(header2) < 8:
            return False
        _, tag2 = struct.unpack(">I4s", header2)
        return tag2 == b"moov"


def main():
    if not SUPABASE_URL:
        print("❌ Error: SUPABASE_URL is not set.")
        sys.exit(1)

    repo_root = Path(__file__).resolve().parent.parent.parent
    frontend_dir = repo_root / "frontend"

    logo_path = frontend_dir / "public" / "icon-512.png"
    mark_path = frontend_dir / "app" / "assets" / "icons" / "mark.svg"
    video_path = frontend_dir / "public" / "videos" / "negotiation-demo.mp4"

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
        {
            "local_path": video_path,
            "storage_path": "videos/negotiation-demo.mp4",
            "content_type": "video/mp4",
        },
    ]

    print(f"🚀 Synchronizing CDN assets to Supabase project: {SUPABASE_URL}")
    print(f"📦 Storage bucket: '{STORAGE_BUCKET}'")

    # Verify files exist
    for asset in assets:
        p: Path = asset["local_path"]
        if not p.exists():
            print(f"❌ Missing local file: {p}")
            sys.exit(1)

    # Check video FastStart layout
    if not check_faststart(video_path):
        print("⚠️ Notice: Video moov atom is not at index 2. Applying FastStart optimization...")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_faststart = Path(tmp.name)
        subprocess.run(["uvx", "--from", "qtfaststart", "qtfaststart", str(video_path), str(tmp_faststart)], check=True)
        shutil.move(str(tmp_faststart), str(video_path))
        if check_faststart(video_path):
            print("   ✅ Video optimized with FastStart.")
        else:
            print("   ⚠️ Proceeding with existing video layout.")
    else:
        print("✅ Video confirmed FastStart-optimized (moov atom at head).")

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

    print("\n🔍 Verifying CDN endpoints and HTTP Range streaming...")
    with httpx.Client(timeout=15.0) as client:
        for storage_path, url, content_type in uploaded_urls:
            # Test HEAD or GET range request
            if "video" in content_type:
                resp = client.get(url, headers={"Range": "bytes=0-1024"})
                is_ok = resp.status_code in (200, 206)
                stream_support = "✅ (HTTP 206 Byte-Range streaming active)" if resp.status_code == 206 else "⚠️ HTTP 200"
                print(f"   📹 {storage_path}: Status {resp.status_code} {stream_support}")
            else:
                resp = client.get(url)
                is_ok = resp.status_code == 200
                status_icon = "✅" if is_ok else "❌"
                print(f"   🖼️  {storage_path}: Status {resp.status_code} {status_icon}")

            if not is_ok:
                print(f"   ⚠️ Warning: Unexpected status code {resp.status_code} for {url}")

    print("\n🎉 CDN Assets successfully synced to Supabase Storage!")
    for storage_path, url, _ in uploaded_urls:
        print(f"   🔗 {storage_path}: {url}")


if __name__ == "__main__":
    main()
