import re
from decimal import Decimal
from datetime import date, datetime
from schemas import (AssetClass, ExtractDocument, ParsedStatement, Position,
                     RawFact, Transaction, TransactionType)
from verify import verify_fact

DATE_FORMATS = {
    "de": ["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"],
    "en": ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"],
}

EVENT_LABELS = {
    "kauf": TransactionType.BUY, "buy": TransactionType.BUY,
    "sparplanausführung": TransactionType.BUY,
    "verkauf": TransactionType.SELL, "sell": TransactionType.SELL,
    "dividende": TransactionType.DIVIDEND, "dividend": TransactionType.DIVIDEND,
}

def parse_number(raw: str, locale: str = "en") -> Decimal:
    s = raw.strip()
    negative = s.startswith("(") or s.startswith("-")
    s = re.sub(r"[^\d,.]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):          # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                    # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if locale == "de" else s.replace(",", "")
    value = Decimal(s)
    return -value if negative else value


def parse_date(raw: str, locale: str) -> date | None:
    text = " ".join(raw.split())                  # fixes "24 Oct\n2026"
    for fmt in DATE_FORMATS[locale]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _asset_class(fact: RawFact, doc: ExtractDocument) -> AssetClass:
    name = f"{fact.instrument or ''} {fact.raw_label}".lower()
    if "etf" in name:
        return AssetClass.ETF
    if fact.kind == "holding" and "deposit" in f"{name} {doc.doc_description}".lower():
        return AssetClass.FIXED_DEPOSIT
    if fact.kind == "event" and not fact.instrument:
        return AssetClass.CASH
    return AssetClass.OTHER


def normalize(doc: ExtractDocument, source_text: str, account_name: str) -> ParsedStatement:
    locale = "de" if (doc.language or "").lower() in ("de", "german", "deutsch") else "en"
    transactions, positions, warnings = [], [], []

    for fact in doc.facts:
        if fact.kind == "balance":
            continue                              # not stored yet
        flags = verify_fact(fact, source_text)
        try:
            if not fact.amount_raw:
                raise ValueError("missing amount")
            amount = parse_number(fact.amount_raw, locale)
            when = parse_date(fact.date_raw, locale) if fact.date_raw else None
            if not fact.currency:
                flags.append("currency_missing_assumed_EUR")
            currency = (fact.currency or "EUR").upper()

            if fact.kind == "event":
                ttype = EVENT_LABELS.get(fact.raw_label.strip().lower())
                if ttype is None:
                    flags.append(f"unknown_label:{fact.raw_label}")
                    ttype = TransactionType.UNKNOWN
                if when is None:
                    raise ValueError(f"unparseable date {fact.date_raw!r}")
                transactions.append(Transaction(
                    transaction_date=when, transaction_type=ttype,
                    asset_class=_asset_class(fact, doc),
                    instrument_name=fact.instrument, isin=fact.isin,
                    quantity=parse_number(fact.quantity_raw, locale) if fact.quantity_raw else None,
                    amount=amount, currency=currency,
                    description=fact.evidence.quote, flags=flags))
            else:
                positions.append(Position(
                    instrument_name=fact.instrument or fact.raw_label,
                    asset_class=_asset_class(fact, doc), currency=currency,
                    value=amount, as_of_date=when,
                    details={a.key: a.value for a in fact.attributes},
                    description=fact.evidence.quote, flags=flags))
        except (ValueError, ArithmeticError) as e:   # ArithmeticError: bad number
            warnings.append(f"Skipped '{fact.raw_label}': {e}")

    return ParsedStatement(account_name=account_name, transactions=transactions,
                           positions=positions, warnings=warnings)