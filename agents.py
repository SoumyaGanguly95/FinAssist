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

from langchain.agents import create_agent
from langchain.tools import tool
from sqlalchemy import func, select

from models import Account, TransactionRecord, get_session
from schemas import ParsedStatement

# --- Parsing agent -------------------------------------------------------
# Single-pass structured extraction: statement text in, ParsedStatement out.
# No tools, no loop — there's no multi-step reasoning needed here.

PARSING_SYSTEM_PROMPT = """You are a financial statement parser. You will be
given raw text extracted from a brokerage or bank statement. Extract every
transaction line item into the required structure.

Rules:
- Do not invent transactions that aren't present in the text.
- If a field genuinely isn't present in the source text, leave it null
  rather than guessing.
- Preserve the original description text for each transaction so it can
  be audited against the source statement.
- Infer transaction_type from context (e.g. "Kauf" / "Buy" -> buy;
  "Savings plan execution" -> buy; incoming transfer -> deposit; outgoing
  transfer -> withdrawal).
- asset_class classification — check the description text carefully:
  * If the description contains "ETF" or "UCITS ETF" -> asset_class is
    "etf" (NOT "other" — this is a common mistake, double-check every
    buy/sell transaction against this rule before finalizing).
  * If it names a specific company stock with no "ETF"/"Fund" wording
    -> "equity".
  * If it's a cash movement (deposit, withdrawal, interest, fee) with no
    instrument -> "cash".
  * "Fonds"/"Fund" in the name without "ETF" -> treat as "etf" if it's a
    UCITS/index fund, otherwise leave as "other" only as a last resort.
- Do not fabricate an instrument name if the statement doesn't name one.
"""


def parse_statement_text(raw_text: str, account_hint: str | None = None) -> ParsedStatement:
    """Verify the model string against current LangChain/Azure OpenAI docs
    before running — provider integration strings change as new models ship.
    """
    agent = create_agent(
        model="openai:gpt-4.1-mini",
        tools=[],
        system_prompt=PARSING_SYSTEM_PROMPT,
        response_format=ParsedStatement,
    )
    content = raw_text
    if account_hint:
        content = f"[This statement is from account: {account_hint}]\n\n{raw_text}"

    result = agent.invoke({"messages": [{"role": "user", "content": content}]})
    return result["structured_response"]


# --- Insight agent tools ---------------------------------------------------
# Each tool is a plain function the insight agent can choose to call.


@tool
def query_holdings(account_name: str | None = None) -> str:
    """Return current holdings, optionally filtered to one account. Use
    this when the user asks what they own, their allocation, or anything
    about specific instruments/positions."""
    with get_session() as session:
        stmt = select(
            TransactionRecord.instrument_name,
            TransactionRecord.asset_class,
            func.sum(TransactionRecord.quantity).label("net_quantity"),
        ).group_by(TransactionRecord.instrument_name, TransactionRecord.asset_class)
        if account_name:
            stmt = stmt.join(TransactionRecord.account).where(Account.name == account_name)
        rows = session.execute(stmt).all()
        if not rows:
            return "No holdings found."
        return "\n".join(
            f"{r.instrument_name or 'unnamed'} ({r.asset_class}): {r.net_quantity}" for r in rows
        )


@tool
def get_portfolio_valuation() -> str:
    """Return the total portfolio value / net cash flow summary. Use this
    when the user asks about total value, growth, or overall performance."""
    with get_session() as session:
        total = session.execute(select(func.sum(TransactionRecord.amount))).scalar_one_or_none()
        return f"Net cash flow across all recorded transactions: {total or 0}"


@tool
def flag_anomaly(description: str, reason: str) -> str:
    """Record a potential anomaly for human review (e.g. an unexpected
    fee, a duplicate-looking transaction). Does not take destructive
    action — only logs the flag."""
    print(f"[ANOMALY FLAGGED] {description} — {reason}")
    return "Anomaly recorded for review."


INSIGHT_TOOLS = [query_holdings, get_portfolio_valuation, flag_anomaly]

# --- Insight agent --------------------------------------------------------
# Multi-step, tool-calling agent — this is the piece that actually needs
# LangGraph's loop (decide which tool to call, inspect result, decide again).

INSIGHT_SYSTEM_PROMPT = """You are a financial insight assistant for a
single user's personal investment portfolio. Answer questions using the
tools available to you — do not guess numbers. If a question requires
data you don't have a tool for, say so rather than fabricating an answer.
Be concise. This is not financial advice; if the user asks for a
recommendation, frame your answer as information to help them decide,
not as a directive.
"""


def run_insight_query(question: str, thread_id: str = "default") -> str:
    agent = create_agent(
        model="openai:gpt-4.1-mini",
        tools=INSIGHT_TOOLS,
        system_prompt=INSIGHT_SYSTEM_PROMPT,
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content