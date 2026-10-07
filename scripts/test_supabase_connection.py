"""Utility script to verify Supabase PostgreSQL connection and table schemas."""

import argparse
import sys
import time

from sqlalchemy import inspect, text

from src.core.config import settings
from src.core.database import build_engine, init_db


def mask_connection_url(url: str) -> str:
    """Mask credentials in database URL for safe logging."""
    if "@" not in url:
        return url
    prefix, suffix = url.split("@", 1)
    if "://" in prefix:
        scheme, userpass = prefix.split("://", 1)
        if ":" in userpass:
            user = userpass.split(":", 1)[0]
            return f"{scheme}://{user}:***@{suffix}"
        return f"{scheme}://***@{suffix}"
    return f"***@{suffix}"


def verify_connection(url: str, apply_migrations: bool = False) -> bool:
    """Validate database connectivity, vector extension, and schema tables."""
    print("=" * 60)
    print("Testing Supabase Database Connection")
    print(f"Target URL: {mask_connection_url(url)}")
    print("=" * 60)

    start_time = time.time()
    try:
        engine = build_engine(url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();")).scalar()
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            print(f"[SUCCESS] Connected in {elapsed_ms}ms")
            print(f"PostgreSQL Version: {result}")
    except Exception as exc:
        print(f"[FAILURE] Unable to connect to database: {exc}")
        print("\nTroubleshooting tips for Supabase:")
        print("1. If using password with special characters, URL-encode them.")
        print("2. In cloud environments without IPv6, use the Supavisor Pooler URL:")
        print("   Host: aws-0-[region].pooler.supabase.com")
        print("   Port: 6543 (Transaction) or 5432 (Session)")
        print("3. Ensure '?sslmode=require' is present in your connection string.")
        return False

    # Check pgvector extension
    try:
        with engine.connect() as conn:
            vector_check = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
            ).scalar()
            if vector_check:
                print("[SUCCESS] pgvector extension is installed and active")
            else:
                print("[INFO] pgvector extension not yet enabled. Attempting creation...")
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    conn.commit()
                    print("[SUCCESS] pgvector extension created successfully")
                except Exception as ext_err:
                    print(f"[WARNING] Could not create pgvector extension: {ext_err}")
    except Exception as exc:
        print(f"[WARNING] Extension check encountered: {exc}")

    # Inspect tables
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = {
        "articles",
        "cluster_runs",
        "story_clusters",
        "scripts",
        "render_jobs",
        "cost_log",
        "action_logs",
        "visual_assets",
    }
    missing_tables = expected_tables - existing_tables

    print(f"\nDiscovered {len(existing_tables)} existing tables: {sorted(list(existing_tables))}")
    if missing_tables:
        print(f"[INFO] Missing required tables: {sorted(list(missing_tables))}")
        if apply_migrations:
            print("Applying schema initialization via init_db()...")
            try:
                init_db(target_engine=engine)
                updated_tables = set(inspect(engine).get_table_names())
                still_missing = expected_tables - updated_tables
                if not still_missing:
                    print("[SUCCESS] All tables successfully created in Supabase")
                else:
                    print(f"[WARNING] Still missing tables: {sorted(list(still_missing))}")
            except Exception as init_err:
                print(f"[FAILURE] Error initializing tables: {init_err}")
                return False
        else:
            print("Run with --migrate flag or run scripts/supabase_schema.sql to build tables.")
    else:
        print("[SUCCESS] All required application tables exist in Supabase")

    # Perform a light read/write transaction check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
            print("[SUCCESS] Read/write transaction validation passed")
    except Exception as tx_err:
        print(f"[FAILURE] Transaction test failed: {tx_err}")
        return False

    print("\nDatabase configuration is ready for Hugging Face Spaces deployment.")
    return True


def main() -> None:
    """CLI entrypoint for Supabase connection verification."""
    parser = argparse.ArgumentParser(
        description="Verify Supabase PostgreSQL connection and table schemas."
    )
    parser.add_argument(
        "database_url",
        nargs="?",
        default=None,
        help="Supabase database URL (defaults to DATABASE_URL from environment or config)",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Automatically provision missing tables if they do not exist",
    )
    args = parser.parse_args()

    target_url = args.database_url or settings.database_url
    if not target_url:
        print("[ERROR] No DATABASE_URL provided. Pass URL or set DATABASE_URL in environment.")
        sys.exit(1)

    success = verify_connection(target_url, apply_migrations=args.migrate)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
