"""
CLI wrapper around the same ingest_statement() the API uses — fastest
feedback loop while iterating on the parsing agent's prompt or schema.

Usage:
    uv run python scripts/cli_ingest.py data/raw/statement.pdf
    uv run python scripts/cli_ingest.py data/raw/statement.pdf --account "Trade Republic" --commit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running this script directly without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import commit_parsed_statement, ingest_statement  # noqa: E402
from models import init_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a single statement file")
    parser.add_argument("file_path")
    parser.add_argument("--account", dest="account_hint", default=None)
    parser.add_argument("--commit", action="store_true", help="Write to the database")
    args = parser.parse_args()

    parsed = ingest_statement(args.file_path, account_hint=args.account_hint)
    print(json.dumps(parsed.model_dump(mode="json"), indent=2))

    if args.commit:
        init_db()
        result = commit_parsed_statement(parsed, source_file=args.file_path)
        print(f"\nCommitted: {result}")
    else:
        print("\n(dry run — pass --commit to write to the database)")


if __name__ == "__main__":
    main()