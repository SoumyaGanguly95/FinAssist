"""
Ingestion pipeline: extract text -> parse via agent -> (separately) persist
to the database. Two distinct functions on purpose — ingest_statement()
only parses and returns data for review; commit_parsed_statement() is the
explicit "yes, save this" step. Never auto-chain them — see README.md on
human-in-the-loop review before financial data is persisted.

This file has no Streamlit or FastAPI imports, so the exact same functions
are called from app.py (the API), scripts/cli_ingest.py, and later an
Azure Function triggered by Blob Storage — only the trigger changes.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber
from sqlalchemy import select

from agents import parse_statement_text
from models import Account, TransactionRecord, get_session
from schemas import ParsedStatement


def extract_text(file_path: str) -> str:
    """Returns raw text for the parsing agent to interpret.

    PDF: extracted via pdfplumber (statements aren't machine-readable text
    otherwise).
    CSV: read as-is and handed to the same agent as raw text. This works
    for testing, but it's not the efficient long-term approach — CSV data
    is ALREADY structured, so routing it through an LLM to re-structure it
    burns tokens for no real gain, and gives the agent a chance to
    misread a column. Once you know your broker's actual CSV column
    layout, replace this branch with a deterministic pandas-based parser
    (see the note in README.md roadmap) — reserve the LLM path for PDFs,
    where OCR/layout genuinely requires interpretation.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text_parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)

    if suffix == ".csv":
        return path.read_text(encoding="utf-8", errors="replace")

    raise ValueError(f"extract_text supports .pdf and .csv, got: {suffix}")


def ingest_statement(file_path: str, account_hint: str | None = None) -> ParsedStatement:
    """File in, validated structured output out. Does NOT write to the DB."""
    raw_text = extract_text(file_path)
    if not raw_text.strip():
        raise ValueError(f"No extractable text in {file_path} — is it a scanned image?")
    return parse_statement_text(raw_text, account_hint=account_hint)


def commit_parsed_statement(parsed: ParsedStatement, source_file: str) -> dict:
    """Writes transactions to the DB, skipping any that already exist
    (dedup via content_hash — see schemas.py / models.py)."""
    inserted, skipped = 0, 0
    with get_session() as session:
        account = session.execute(
            select(Account).where(Account.name == parsed.account_name)
        ).scalar_one_or_none()
        if account is None:
            account = Account(name=parsed.account_name)
            session.add(account)
            session.flush()

        existing_hashes = {
            row[0]
            for row in session.execute(
                select(TransactionRecord.content_hash).where(
                    TransactionRecord.account_id == account.id
                )
            ).all()
        }

        for txn in parsed.transactions:
            content_hash = txn.content_hash(parsed.account_name)
            if content_hash in existing_hashes:
                skipped += 1
                continue
            session.add(
                TransactionRecord(
                    account_id=account.id,
                    transaction_date=txn.transaction_date,
                    transaction_type=txn.transaction_type.value,
                    asset_class=txn.asset_class.value,
                    instrument_name=txn.instrument_name,
                    isin=txn.isin,
                    quantity=txn.quantity,
                    amount=txn.amount,
                    currency=txn.currency,
                    description=txn.description,
                    content_hash=content_hash,
                    source_file=source_file,
                )
            )
            inserted += 1

    return {"inserted": inserted, "skipped_duplicates": skipped}