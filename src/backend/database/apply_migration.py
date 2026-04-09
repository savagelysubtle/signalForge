"""Apply a single SQL migration file using DATABASE_URL.

Requires a **direct Postgres** connection string (not the PostgREST URL).
For Supabase: Dashboard → Project Settings → Database → Connection string
→ **URI** → use **Session mode** (port **5432**) or the pooler with user
``postgres.<project-ref>`` and correct password.

Usage (from repo root, with ``DATABASE_URL`` in ``.env``)::

    # Python 3.12+ recommended (free-threaded 3.14 may lack psycopg wheels):
    pip install "psycopg[binary]" python-dotenv
    python src/backend/database/apply_migration.py 022_strategy_listing_currency.sql

Or paste the migration body into Supabase **SQL Editor** → Run.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    try:
        import psycopg
        from dotenv import load_dotenv
    except ImportError as exc:
        print("Install dependencies: pip install psycopg[binary] python-dotenv", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description="Apply a SQL migration via DATABASE_URL.")
    parser.add_argument(
        "migration",
        help="Migration filename under database/migrations/ (e.g. 022_strategy_listing_currency.sql)",
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent.parent
    repo_root = backend_dir.parent.parent
    load_dotenv(repo_root / ".env")

    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    mig_name = args.migration
    if "/" in mig_name or "\\" in mig_name:
        path = Path(mig_name)
    else:
        path = Path(__file__).resolve().parent / "migrations" / mig_name

    if not path.is_file():
        print(f"Migration file not found: {path}", file=sys.stderr)
        return 1

    sql = path.read_text(encoding="utf-8")
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    parts = [p.strip() for p in body.split(";") if p.strip()]

    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for stmt in parts:
                conn.execute(stmt)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1

    print(f"Applied {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
