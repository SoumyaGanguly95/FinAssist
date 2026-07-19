"""
Creates the local SQLite database and tables, using the models defined in
models.py. Safe to run multiple times — create_all() only creates tables
that don't already exist, it won't wipe existing data.

Usage:
    uv run python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import DATABASE_URL, init_db  # noqa: E402


def main() -> None:
    print(f"Initializing database at: {DATABASE_URL}")
    init_db()
    print("Done. Tables created (or already existed).")


if __name__ == "__main__":
    main()