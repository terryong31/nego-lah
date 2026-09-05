"""
Migration runner for Nego-lah Supabase database.
Executes SQL migrations from supabase/migrations/ in alphanumeric order against DATABASE_URL.
Tracks applied versions in `supabase_migrations.schema_migrations` so re-runs are idempotent.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg


async def run_migrations():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL is not set.")
        sys.exit(1)

    repo_root = Path(__file__).resolve().parent.parent.parent
    migrations_dir = repo_root / "supabase" / "migrations"

    if not migrations_dir.exists():
        print(f"❌ Error: Migrations directory not found at {migrations_dir}")
        sys.exit(1)

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        print(f"❌ Error: No .sql migration files found in {migrations_dir}")
        sys.exit(1)

    safe_target = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"🚀 Connecting to database: {safe_target}")

    conn = await asyncpg.connect(db_url, ssl="require")
    try:
        # 1. Ensure migrations schema and tracking table exist
        await conn.execute(
            """
            CREATE SCHEMA IF NOT EXISTS supabase_migrations;
            CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations (
                version text PRIMARY KEY,
                name text,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )

        # 2. Fetch already-applied versions
        rows = await conn.fetch("SELECT version FROM supabase_migrations.schema_migrations;")
        applied_versions = {r["version"] for r in rows}

        # If tracking table is empty but public.items already exists, pre-seed applied files
        if not applied_versions:
            has_items = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'items';"
            )
            has_idempotency = await conn.fetchval(
                "SELECT 1 FROM pg_constraint WHERE conname = 'orders_stripe_payment_id_key';"
            )
            if has_items and has_idempotency:
                print("ℹ️ Existing schema detected; synchronizing migration tracking state...")
                for f in migration_files:
                    version = f.stem.split("_")[0]
                    await conn.execute(
                        "INSERT INTO supabase_migrations.schema_migrations (version, name) VALUES ($1, $2) ON CONFLICT DO NOTHING;",
                        version, f.name
                    )
                    applied_versions.add(version)

        print(f"📦 Found {len(migration_files)} migration files ({len(applied_versions)} already recorded).\n")

        # 3. Apply pending migrations
        applied_count = 0
        for f in migration_files:
            version = f.stem.split("_")[0]
            if version in applied_versions:
                print(f"   ⏭️  Already applied: {f.name}")
                continue

            print(f"\n▶️ Applying pending: {f.name}...")
            sql_content = f.read_text(encoding="utf-8")

            async with conn.transaction():
                await conn.execute(sql_content)
                await conn.execute(
                    "INSERT INTO supabase_migrations.schema_migrations (version, name) VALUES ($1, $2);",
                    version, f.name
                )
            print(f"   ✅ Successfully applied: {f.name}")
            applied_count += 1
            applied_versions.add(version)

        if applied_count == 0:
            print("\n✨ Database schema is fully up to date!")
        else:
            await conn.execute("NOTIFY pgrst, 'reload schema';")
            print("   🔄 Notified PostgREST to reload schema cache.")
            print(f"\n🎉 Successfully applied {applied_count} pending migrations!")

        # 4. Schema verification summary
        print("\n📊 Schema Summary:")
        tables = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
            """
        )
        print(f"   Public tables ({len(tables)}):")
        for row in tables:
            tname = row["table_name"]
            count = await conn.fetchval(f'SELECT count(*) FROM public."{tname}"')  # noqa: S608 # nosec B608
            rls_enabled = await conn.fetchval(
                "SELECT relrowsecurity FROM pg_class WHERE relname = $1",
                tname
            )
            rls_status = "RLS enabled" if rls_enabled else "RLS disabled"
            print(f"     - {tname:20} (rows: {count:3}, {rls_status})")

        buckets = await conn.fetch("SELECT id, name, public FROM storage.buckets;")
        print(f"\n   Storage buckets ({len(buckets)}):")
        for b in buckets:
            print(f"     - {b['id']} (public: {b['public']})")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
