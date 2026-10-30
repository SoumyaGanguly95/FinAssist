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


class Attribute(BaseModel):
    key: str
    value: str


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
    FIXED_DEPOSIT = "fixed_deposit"
    OTHER = "other"


class Transaction(BaseModel):
    transaction_date: date = Field(description="ISO date YYYY-MM-DD")
    transaction_type: TransactionType
    asset_class: AssetClass
    instrument_name: str | None = None
    isin: str | None = None
    quantity: Decimal | None = Field(default=None, description="Plain decimal number")
    amount: Decimal = Field(description="Signed plain decimal: negative = leaves the account, positive = enters it")
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code")
    balance_after: Decimal | None = Field(default=None, description="Running balance after this line, only if the document shows one")
    description: str = Field(description="Source text of this line, copied verbatim")

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper()

    def content_hash(self, account_name: str) -> str:
        desc = " ".join(self.description.split())
        key = f"{account_name}|{self.transaction_date}|{self.amount:.2f}|{self.quantity}|{self.isin}|{desc}"
        return hashlib.sha256(key.encode()).hexdigest()


class Position(BaseModel):
    instrument_name: str
    asset_class: AssetClass
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code")
    value: Decimal = Field(description="Principal or market value, plain decimal")
    as_of_date: date | None = Field(default=None, description="Start date or valuation date, ISO YYYY-MM-DD")
    reference: str | None = Field(default=None, description="Last 4 characters of the account / deposit / contract number")
    details: list[Attribute] = Field(default=[], description="Other facts, snake_case keys, e.g. maturity_date (ISO), maturity_amount, interest_rate")
    description: str = Field(description="Source text of this item, copied verbatim")

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.upper()

    def content_hash(self, account_name: str) -> str:
        key = f"{account_name}|{self.instrument_name.strip().lower()}|{self.value:.2f}|{self.currency}|{self.as_of_date}|{self.reference}"
        return hashlib.sha256(key.encode()).hexdigest()


class ExtractDocument(BaseModel):
    """What the LLM returns."""
    account_name: str
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    transactions: list[Transaction] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)


class ParsedStatement(ExtractDocument):
    """What the API returns and commits: the LLM result plus system-generated warnings."""
    warnings: list[str] = Field(default_factory=list)