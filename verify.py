import re

from schemas import ExtractDocument


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def verify(doc: ExtractDocument, source_text: str) -> list[str]:
    """Returns warnings only. Never rejects or changes data."""
    warnings = []
    source = _clean(source_text)

    for i, t in enumerate(doc.transactions, 1):
        if _clean(t.description) not in source:
            warnings.append(f"Transaction {i} ({t.transaction_date}, {t.amount}): text not found in source")
    for i, p in enumerate(doc.positions, 1):
        if _clean(p.description) not in source:
            warnings.append(f"Position {i} ({p.instrument_name}, {p.value}): text not found in source")

    # Running-balance check: works in any country; direction-agnostic (newest-first or oldest-first)
    if doc.transactions and all(t.balance_after is not None for t in doc.transactions):
        for a, b in zip(doc.transactions, doc.transactions[1:]):
            forward = a.balance_after + b.amount == b.balance_after
            backward = b.balance_after + a.amount == a.balance_after
            if not (forward or backward):
                warnings.append(f"Balance does not follow between {a.transaction_date} and {b.transaction_date}")
    return warnings