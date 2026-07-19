"""
Placeholder — fill in once you've run the parsing agent against a real
statement and know what its actual output shape looks like. Writing
detailed tests before that would just be testing guesses.
"""

from schemas import ParsedStatement, Transaction, TransactionType, AssetClass


def test_transaction_content_hash_is_stable():
    t1 = Transaction(
        transaction_date="2026-01-15",
        transaction_type=TransactionType.BUY,
        asset_class=AssetClass.ETF,
        amount=-100.00,
        description="Buy VWCE",
    )
    t2 = Transaction(**t1.model_dump())
    assert t1.content_hash("Trade Republic") == t2.content_hash("Trade Republic")


def test_parsed_statement_requires_transactions_list():
    stmt = ParsedStatement(account_name="Trade Republic", transactions=[])
    assert stmt.transactions == []