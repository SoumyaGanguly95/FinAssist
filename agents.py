"""
All agent logic in one file: the parsing agent (single-pass structured
extraction), the insight agent's tools, and the insight agent itself
(multi-step tool-calling). Split into three files only once this grows
past ~200-300 lines — at MVP size, one file is easier to navigate than
jumping between agents/parsing_agent.py, agents/tools.py, agents/insight_agent.py.

Uses LangChain 1.0's create_agent (built on LangGraph). See:
https://docs.langchain.com/oss/python/langchain/agents
"""

from __future__ import annotations

from datetime import date

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import func, select

from models import get_session, Account, TransactionRecord, HoldingRecord
from schemas import ExtractDocument

# --- Parsing agent -------------------------------------------------------
# Single-pass structured extraction: statement text in, ParsedStatement out.
# No tools, no loop — there's no multi-step reasoning needed here.

EXTRACTION_SYSTEM_PROMPT = """You extract structured data from financial statements.
  Return valid JSON that matches the schema exactly. Do not add explanation.

  Required JSON shape:
  {
    "account_name": "string",
    "statement_period_start": "YYYY-MM-DD or null",
    "statement_period_end": "YYYY-MM-DD or null",
    "transactions": [
      {
        "transaction_date": "YYYY-MM-DD",
        "transaction_type": "buy|sell|dividend|fee|deposit|withdrawal|interest|unknown",
        "asset_class": "equity|etf|bond|commodity|cash|fixed_deposit|other",
        "instrument_name": "string or null",
        "isin": "string or null",
        "quantity": "number or null",
        "amount": "number",
        "currency": "ISO 4217 code such as EUR, USD, GBP",
        "balance_after": "number or null",
        "description": "verbatim source text"

      }
    ],
    "positions": [
      {
        "instrument_name": "string",
        "asset_class": "equity|etf|bond|commodity|cash|fixed_deposit|other",
        "currency": "ISO 4217 code",
        "value": "number",
        "as_of_date": "YYYY-MM-DD or null",
        "reference": "string or null",
        "details": [{"key": "string", "value": "string"}],
        "description": "verbatim source text"
      }
    ]
  }

  Rules:
  - Output ONLY JSON. No markdown fences, no commentary.
  - Every transaction object MUST include: transaction_date, transaction_type, asset_class, amount, currency, description.
  - Every position object MUST include: instrument_name, asset_class, currency, value, description.
  - If a value is missing, use null instead of inventing it.
  - Dates: ISO YYYY-MM-DD.
  - Numbers: decimal numbers, not strings; no thousands separators.
  - Amount sign: negative when money leaves the account (buy, fee, withdrawal); positive when it enters (deposit, dividend, interest, sale).
  - transaction_type and asset_class must use the exact enum values above.
  - transactions are dated events; positions are holdings as of a date. Never convert one into the other.
  - Skip totals and summary rows. Only keep real transaction or position rows.
  - Copy description verbatim from the source line.
  """

STRICT_EXTRACTION_SYSTEM_PROMPT = """You are a strict data extractor. Return JSON only.
  Never omit required fields. Use exact enum values.
  If a field is unknown, set it to null.

  Schema:
  - account_name: string
  - statement_period_start: date or null
  - statement_period_end: date or null
  - transactions: array of objects with required keys: transaction_date, transaction_type, asset_class, amount, currency, description
  - positions: array of objects with required keys: instrument_name, asset_class, currency, value, description

  Allowed transaction_type values: buy, sell, dividend, fee, deposit, withdrawal, interest, unknown
  Allowed asset_class values: equity, etf, bond, commodity, cash, fixed_deposit, other

  Do not generate prose or markdown. Ensure all JSON keys are present exactly as specified.
  """


def extract_document(raw_text: str, account_hint: str | None = None) -> ExtractDocument:
      agent = create_agent(
          model="openai:gpt-4.1-mini",
          tools=[],
          system_prompt=EXTRACTION_SYSTEM_PROMPT,
          response_format=ExtractDocument,
      )
      content = f"[Account: {account_hint}]\n\n{raw_text}" if account_hint else raw_text
      try:
          result = agent.invoke({"messages": [{"role": "user", "content": content}]})
          return result["structured_response"]
      except ValueError:
          strict_agent = create_agent(
              model="openai:gpt-4.1-mini",
              tools=[],
              system_prompt=STRICT_EXTRACTION_SYSTEM_PROMPT,
              response_format=ExtractDocument,
          )
          result = strict_agent.invoke({"messages": [{"role": "user", "content": content}]})
          return result["structured_response"]


# --- Insight agent tools ---------------------------------------------------
# Each tool is a plain function the insight agent can choose to call.
@tool
def query_positions(account_name: str | None = None) -> str:
    """Return position snapshots recorded from imported statements. These are
    reported values, optionally filtered to an account. They are not live
    market prices or necessarily the latest value."""
    with get_session() as session:
        stmt = (
            select(HoldingRecord, Account.name.label("account_name"))
            .join(Account, HoldingRecord.account_id == Account.id)
            .order_by(HoldingRecord.as_of_date.desc(), HoldingRecord.id.desc())
        )
        if account_name:
            stmt = stmt.where(Account.name == account_name)
        rows = session.execute(stmt).all()
        if not rows:
            return "No positions found."
        return "\n".join(
            f"{account} | {position.instrument_name} ({position.asset_class}): "
            f"{position.value} {position.currency}, as of {position.as_of_date}, "
            f"{position.details}"
            for position, account in rows
        )


@tool
def query_transactions(
    start_date: date | None = None,
    end_date: date | None = None,
    account_name: str | None = None,
    instrument_name: str | None = None,
    limit: int = 25,
) -> str:
    """Search imported transactions. Dates are inclusive ISO dates. Optional
    filters restrict by account or partial instrument name. Limit must be
    between 1 and 100. Amounts are reported in each transaction's currency."""
    if start_date and end_date and start_date > end_date:
        return "Invalid date range: start_date must be on or before end_date."
    if not 1 <= limit <= 100:
        return "Invalid limit: choose a value from 1 to 100."

    stmt = (
        select(TransactionRecord, Account.name.label("account_name"))
        .join(Account, TransactionRecord.account_id == Account.id)
        .order_by(TransactionRecord.transaction_date.desc(), TransactionRecord.id.desc())
        .limit(limit)
    )
    if start_date:
        stmt = stmt.where(TransactionRecord.transaction_date >= start_date)
    if end_date:
        stmt = stmt.where(TransactionRecord.transaction_date <= end_date)
    if account_name:
        stmt = stmt.where(Account.name == account_name)
    if instrument_name:
        stmt = stmt.where(TransactionRecord.instrument_name.ilike(f"%{instrument_name}%"))

    with get_session() as session:
        rows = session.execute(stmt).all()
        if not rows:
            return "No matching transactions found."
        return "\n".join(
            f"{account_name} | {record.transaction_date} | {record.transaction_type} | "
            f"{record.instrument_name or 'unnamed'} ({record.asset_class}) | "
            f"{record.quantity if record.quantity is not None else 'quantity unavailable'} units | "
            f"{record.amount} {record.currency} | {record.description}"
            for record, account_name in rows
        )


@tool
def get_net_cash_flow() -> str:
    """Return the sum of recorded transaction amounts (net cash flow), not
    current portfolio value or investment performance. Use only for questions
    explicitly about recorded cash flows."""
    with get_session() as session:
        rows = session.execute(
            select(TransactionRecord.currency, func.sum(TransactionRecord.amount))
            .group_by(TransactionRecord.currency)
        ).all()
        if not rows:
            return "No transactions found."
        return "\n".join(
            f"Recorded net cash flow: {total or 0} {currency}"
            for currency, total in rows
        )


INSIGHT_TOOLS = [query_transactions, get_net_cash_flow, query_positions]

# --- Insight agent --------------------------------------------------------
# Multi-step, tool-calling agent — this is the piece that actually needs
# LangGraph's loop (decide which tool to call, inspect result, decide again).

INSIGHT_SYSTEM_PROMPT = """You are a financial data assistant for a
single user's personal portfolio. Answer using the available database tools;
never invent records, amounts, dates, or currencies. Ask a concise clarifying
question when a filter is ambiguous. State when data is missing or incomplete.
Position values are snapshots from uploaded statements, not live market
prices. Net cash flow is not portfolio value, return, or profit/loss. Never
combine amounts across currencies. This is not financial advice; frame
recommendations as neutral information, not directives.
"""


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content)


def conversation_messages(messages: list[object]) -> list[dict[str, str]]:
    """Convert checkpoint messages to user-facing text, hiding tool exchanges."""
    result = []
    for message in messages:
        message_type = getattr(message, "type", None)
        if message_type == "human":
            role = "user"
        elif message_type == "ai" and not getattr(message, "tool_calls", []):
            role = "assistant"
        else:
            continue
        content = _message_text(getattr(message, "content", ""))
        if content:
            result.append({"role": role, "content": content})
    return result


def build_insight_agent(
    checkpointer: BaseCheckpointSaver,
    model: str | BaseChatModel = "openai:gpt-4.1-mini",
    tools=INSIGHT_TOOLS,
):
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=INSIGHT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def get_insight_conversation(
    thread_id: str,
    checkpointer: BaseCheckpointSaver,
) -> list[dict[str, str]]:
    agent = build_insight_agent(checkpointer)
    state = agent.get_state({"configurable": {"thread_id": thread_id}})
    return conversation_messages(state.values.get("messages", []))


def run_insight_query(
    message: str,
    thread_id: str,
    checkpointer: BaseCheckpointSaver,
) -> str:
    agent = build_insight_agent(checkpointer)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content