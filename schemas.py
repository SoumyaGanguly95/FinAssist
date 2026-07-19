"""
Pydantic models: the validation contract between the parsing agent's raw
LLM output and the database. Kept separate from models.py (SQLAlchemy)
deliberately — this validates untrusted agent output BEFORE it's allowed
to become a persisted row.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TransactionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST = "interest"
    UNKNOWN = "unknown"


class AssetClass(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    BOND = "bond"
    COMMODITY = "commodity"
    CASH = "cash"
    OTHER = "other"


class Transaction(BaseModel):
    transaction_date: date
    transaction_type: TransactionType
    asset_class: AssetClass
    instrument_name: str | None = None
    isin: str | None = None
    quantity: Decimal | None = None
    amount: Decimal = Field(description="Signed amount in the statement's currency")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    description: str = Field(description="Raw line item text, for audit/debugging")

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper()

    def content_hash(self, account_name: str) -> str:
        """Stable hash used to dedup on ingest — see models.py unique
        constraint. account_name is passed in from the parent
        ParsedStatement rather than stored per-transaction, since it's
        the same value for every transaction in a statement."""
        key = f"{account_name}|{self.transaction_date}|{self.amount}|{self.description}"
        return hashlib.sha256(key.encode()).hexdigest()


class ParsedStatement(BaseModel):
    """Top-level structured output the parsing agent must produce."""

    account_name: str
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    transactions: list[Transaction]