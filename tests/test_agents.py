"""
Placeholder — fill in once you've run the parsing agent against a real
statement and know what its actual output shape looks like. Writing
detailed tests before that would just be testing guesses.
"""

from datetime import date
from types import SimpleNamespace

import agents
import ingest
import models
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from schemas import ParsedStatement, Transaction, TransactionType, AssetClass


def test_transaction_content_hash_is_stable():
    t1 = Transaction(
        transaction_date="2026-01-15",
        transaction_type=TransactionType.BUY,
        asset_class=AssetClass.ETF,
        amount=-100.00,
        currency="EUR",
        description="Buy VWCE",
    )
    t2 = Transaction(**t1.model_dump())
    assert t1.content_hash("Trade Republic") == t2.content_hash("Trade Republic")


def test_parsed_statement_requires_transactions_list():
    stmt = ParsedStatement(account_name="Trade Republic", transactions=[])
    assert stmt.transactions == []


def test_insight_query_passes_message_thread_and_checkpointer(monkeypatch):
    checkpointer = object()
    captured = {}

    class FakeAgent:
        def invoke(self, inputs, config):
            captured["inputs"] = inputs
            captured["config"] = config
            return {"messages": [SimpleNamespace(content="answer")]}

    def fake_create_agent(**kwargs):
        captured["agent_kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr(agents, "create_agent", fake_create_agent)

    answer = agents.run_insight_query(
        message="What positions do I have?",
        thread_id="conversation-123",
        checkpointer=checkpointer,
    )

    assert answer == "answer"
    assert captured["agent_kwargs"]["checkpointer"] is checkpointer
    assert captured["inputs"]["messages"] == [
        {"role": "user", "content": "What positions do I have?"}
    ]
    assert captured["config"]["configurable"]["thread_id"] == "conversation-123"


def test_conversation_messages_hide_tool_exchanges():
    messages = agents.conversation_messages([
        HumanMessage(content="Show transactions"),
        AIMessage(content="", tool_calls=[
            {"name": "query_transactions", "args": {}, "id": "call-1", "type": "tool_call"}
        ]),
        ToolMessage(content="transaction row", tool_call_id="call-1"),
        AIMessage(content=[{"type": "text", "text": "Here is the result."}]),
    ])

    assert messages == [
        {"role": "user", "content": "Show transactions"},
        {"role": "assistant", "content": "Here is the result."},
    ]


def test_query_transactions_applies_date_and_instrument_filters(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transactions.sqlite'}")
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(models, "SessionLocal", sessionmaker(bind=engine))

    with models.get_session() as session:
        account = models.Account(name="Broker")
        session.add(account)
        session.flush()
        for transaction_date, instrument in [
            (date.fromisoformat("2026-01-15"), "Example ETF"),
            (date.fromisoformat("2025-12-15"), "Example ETF"),
            (date.fromisoformat("2026-01-20"), "Other fund"),
        ]:
            session.add(models.TransactionRecord(
                account_id=account.id,
                transaction_date=transaction_date,
                transaction_type="buy",
                asset_class="etf",
                instrument_name=instrument,
                isin=None,
                quantity=1,
                amount=-10,
                currency="EUR",
                description=f"Buy {instrument}",
                content_hash=f"{transaction_date}-{instrument}",
                source_file="statement.csv",
            ))

    result = agents.query_transactions.invoke({
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "instrument_name": "Example",
    })

    assert "2026-01-15" in result
    assert "2025-12-15" not in result
    assert "Other fund" not in result


def test_commit_parsed_statement_skips_duplicate_transactions_in_same_batch(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transactions.sqlite'}")
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(models, "SessionLocal", sessionmaker(bind=engine))

    payload = ParsedStatement(
        account_name="Broker",
        transactions=[
            Transaction(
                transaction_date="2026-01-15",
                transaction_type=TransactionType.BUY,
                asset_class=AssetClass.ETF,
                amount=-100.00,
                currency="EUR",
                description="Buy VWCE",
            ),
            Transaction(
                transaction_date="2026-01-15",
                transaction_type=TransactionType.BUY,
                asset_class=AssetClass.ETF,
                amount=-100.00,
                currency="EUR",
                description="Buy VWCE",
            ),
        ],
        positions=[],
    )

    result = ingest.commit_parsed_statement(payload, "statement.csv")

    assert result == {
        "inserted": 1,
        "skipped_duplicates": 1,
        "holdings_inserted": 0,
        "holdings_skipped": 0,
    }


def test_chat_thread_history_survives_checkpointer_reopen(tmp_path):
    checkpoint_path = str(tmp_path / "chat.sqlite")
    thread_id = "conversation-123"
    config = {"configurable": {"thread_id": thread_id}}

    with SqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        checkpointer.setup()
        agent = agents.build_insight_agent(
            checkpointer,
            model=FakeListChatModel(responses=["First answer", "Follow-up answer"]),
            tools=[],
        )
        agent.invoke({"messages": [{"role": "user", "content": "First question"}]}, config)
        agent.invoke({"messages": [{"role": "user", "content": "Follow-up"}]}, config)

    with SqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        checkpointer.setup()
        agent = agents.build_insight_agent(
            checkpointer,
            model=FakeListChatModel(responses=[]),
            tools=[],
        )
        state = agent.get_state(config)

    assert agents.conversation_messages(state.values["messages"]) == [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Follow-up"},
        {"role": "assistant", "content": "Follow-up answer"},
    ]