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

from models import Account, TransactionRecord, get_session
from schemas import ParsedStatement
from verify import verify
from models import HoldingRecord
from agents import extract_document

def _page_text(page) -> str:
    """Text outside tables, then each table as 'cell | cell | cell' rows.
    x_tolerance=1.5 stops words from being glued together."""
    tables = page.find_tables()
    outside = page
    for t in tables:
        outside = outside.outside_bbox(t.bbox)
    parts = [outside.extract_text(x_tolerance=1.5) or ""]
    for t in tables:
        for row in t.extract(x_tolerance=1.5):
            parts.append(" | ".join((c or "").replace("\n", " ").strip() for c in row))
    return "\n".join(p for p in parts if p.strip())

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
        with pdfplumber.open(path) as pdf:
            return "\n".join(_page_text(page) for page in pdf.pages)

    if suffix == ".csv":
        return path.read_text(encoding="utf-8", errors="replace")

    raise ValueError(f"extract_text supports .pdf and .csv, got: {suffix}")


def ingest_statement(file_path: str, account_hint: str | None = None) -> ParsedStatement:
    raw_text = extract_text(file_path)
    if not raw_text.strip():
        raise ValueError(f"No extractable text in {file_path}: is it a scanned image?")
    doc = extract_document(raw_text, account_hint=account_hint)
    if account_hint:
        doc.account_name = account_hint
    if not doc.transactions and not doc.positions:
        raise ValueError("No transactions or positions found in this document")
    return ParsedStatement(**doc.model_dump(), warnings=verify(doc, raw_text))


def commit_parsed_statement(parsed: ParsedStatement, source_file: str) -> dict:
    inserted = skipped = holdings_inserted = holdings_skipped = 0
    with get_session() as session:
        account = session.execute(
            select(Account).where(Account.name == parsed.account_name)
        ).scalar_one_or_none()
        if account is None:
            account = Account(name=parsed.account_name)
            session.add(account)
            session.flush()

        existing = {r[0] for r in session.execute(
            select(TransactionRecord.content_hash).where(TransactionRecord.account_id == account.id)
        ).all()}
        seen_hashes: set[str] = set()

        for txn in parsed.transactions:
            content_hash = txn.content_hash(parsed.account_name)
            if content_hash in existing or content_hash in seen_hashes:
                skipped += 1
                continue
            session.add(TransactionRecord(
                account_id=account.id,
                transaction_date=txn.transaction_date,
                transaction_type=txn.transaction_type.value,
                asset_class=txn.asset_class.value,
                instrument_name=txn.instrument_name,
                isin=txn.isin,
                quantity=txn.quantity,
                amount=txn.amount,
                currency=txn.currency,
                description=txn.description[:500],
                content_hash=content_hash,
                source_file=source_file,
            ))
            existing.add(content_hash)
            seen_hashes.add(content_hash)
            inserted += 1

        existing_holdings = {r[0] for r in session.execute(
            select(HoldingRecord.content_hash).where(HoldingRecord.account_id == account.id)
        ).all()}

        for pos in parsed.positions:
            h = pos.content_hash(parsed.account_name)
            if h in existing_holdings:
                holdings_skipped += 1
                continue
            session.add(HoldingRecord(
                account_id=account.id,
                instrument_name=pos.instrument_name,
                asset_class=pos.asset_class.value,
                currency=pos.currency,
                value=pos.value,
                as_of_date=pos.as_of_date,
                details={a.key: a.value for a in pos.details},
                description=pos.description[:500],
                content_hash=h,
                source_file=source_file,
            ))
            existing_holdings.add(h)
            holdings_inserted += 1

    return {"inserted": inserted, "skipped_duplicates": skipped,
            "holdings_inserted": holdings_inserted, "holdings_skipped": holdings_skipped}