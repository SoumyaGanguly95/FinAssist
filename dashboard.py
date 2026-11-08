"""
Streamlit client — thin by design. All logic lives in app.py/agents.py/
ingest.py; this file only makes HTTP calls and renders results.

Run (with the API running separately: uv run uvicorn app:app --reload):
    uv run streamlit run dashboard.py
"""

import json
import os

import pandas as pd
import requests
import streamlit as st

API_BASE = os.environ.get("FINASSIST_API_URL", "http://localhost:8000")

TX_TYPES = ["buy", "sell", "dividend", "fee", "deposit", "withdrawal", "interest", "unknown"]
ASSET_CLASSES = ["equity", "etf", "bond", "commodity", "cash", "fixed_deposit", "other"]
TX_COLS = ["transaction_date", "transaction_type", "asset_class", "instrument_name", "isin",
           "quantity", "amount", "currency", "balance_after", "description"]
POS_COLS = ["instrument_name", "asset_class", "currency", "value", "as_of_date",
            "reference", "details", "description"]


def details_to_text(details: list[dict]) -> str:
    return json.dumps({d["key"]: d["value"] for d in details})


def text_to_details(text: str | None) -> list[dict]:
    return [{"key": k, "value": str(v)} for k, v in json.loads(text or "{}").items()]


st.set_page_config(page_title="FinAssist", layout="wide")
st.title("FinAssist")

tab_ingest, tab_ask, tab_market = st.tabs(["Ingest statement", "Portfolio chat", "Market watchlist"])

with tab_ingest:
    uploaded = st.file_uploader("Upload a statement (PDF or CSV)", type=["pdf", "csv"])
    account_hint = st.text_input("Account (optional)", placeholder="e.g. Trade Republic")

    if uploaded and st.button("Parse"):
        with st.spinner("Parsing statement..."):
            resp = requests.post(
                f"{API_BASE}/ingest",
                files={"file": (uploaded.name, uploaded.getvalue())},
                params={"account_hint": account_hint} if account_hint else {},
                timeout=120,
            )
        if resp.ok:
            st.session_state["last_parsed"] = resp.json()
        else:
            try:
                st.error(resp.json().get("detail", "Parsing failed"))
            except ValueError:
                st.error(f"API error {resp.status_code}: {resp.text[:500]}")

    if "last_parsed" in st.session_state:
        data = st.session_state["last_parsed"]
        parsed = data["parsed"]
        sid = data["source_file"]            # a new upload gets a fresh editor state

        st.divider()
        st.caption("Edit any cell, add rows at the bottom, or delete rows. "
                   "Confirm saves the table as shown.")
        for w in parsed["warnings"]:
            st.warning(w)
        account_name = st.text_input("Account name", value=parsed["account_name"], key=f"acc_{sid}")

        st.subheader("Transactions")
        tx_edit = st.data_editor(
            pd.DataFrame(parsed["transactions"], columns=TX_COLS),
            num_rows="dynamic", key=f"tx_{sid}",
            column_config={
                "transaction_type": st.column_config.SelectboxColumn(options=TX_TYPES, required=True),
                "asset_class": st.column_config.SelectboxColumn(options=ASSET_CLASSES, required=True),
            },
        )

        st.subheader("Positions")
        pos_rows = [{**p, "details": details_to_text(p["details"])} for p in parsed["positions"]]
        pos_edit = st.data_editor(
            pd.DataFrame(pos_rows, columns=POS_COLS),
            num_rows="dynamic", key=f"pos_{sid}",
            column_config={
                "asset_class": st.column_config.SelectboxColumn(options=ASSET_CLASSES, required=True),
                "details": st.column_config.TextColumn(help='JSON, e.g. {"maturity_date": "2026-10-24"}'),
            },
        )

        if st.button("Confirm and save to database"):
            try:
                positions = json.loads(pos_edit.to_json(orient="records"))
                for p in positions:
                    p["details"] = text_to_details(p["details"])
            except (ValueError, AttributeError) as e:
                st.error(f"'details' must be a JSON object like "
                         f'{{"maturity_date": "2026-10-24"}}. ({e})')
                st.stop()
            payload = {
                **parsed,
                "account_name": account_name,
                "transactions": json.loads(tx_edit.to_json(orient="records")),
                "positions": positions,
            }
            commit_resp = requests.post(
                f"{API_BASE}/ingest/commit", json=payload,
                params={"source_file": sid}, timeout=60,
            )
            if commit_resp.ok:
                st.success(commit_resp.json())
                del st.session_state["last_parsed"]
            else:
                st.error(commit_resp.text)

with tab_ask:
    try:
        conversations_response = requests.get(f"{API_BASE}/conversations", timeout=15)
        conversations_response.raise_for_status()
        conversations = conversations_response.json()["conversations"]
    except (requests.RequestException, ValueError, KeyError) as e:
        st.error(f"Could not load saved conversations: {e}")
        conversations = None

    if conversations is not None:
        conversation_ids = [item["thread_id"] for item in conversations]
        valid_selections = {None, *conversation_ids}

        if st.session_state.get("conversation_selector") not in valid_selections:
            st.session_state["conversation_selector"] = (
                conversation_ids[0] if conversation_ids else None
            )

        if st.button("New conversation", icon=":material/add:"):
            try:
                response = requests.post(f"{API_BASE}/conversations", timeout=15)
                response.raise_for_status()
                thread_id = response.json()["thread_id"]
            except (requests.RequestException, ValueError, KeyError) as e:
                st.error(f"Could not start a conversation: {e}")
            else:
                st.session_state["conversation_selector"] = thread_id
                st.rerun()

        titles = {item["thread_id"]: item["title"] for item in conversations}
        selected_thread_id = st.selectbox(
            "Saved conversations",
            options=[None, *conversation_ids],
            format_func=lambda value: (
                "Choose a conversation" if value is None
                else f"{titles[value]} · {value[:8]}"
            ),
            key="conversation_selector",
        )

        messages = []
        if selected_thread_id:
            try:
                history_response = requests.get(
                    f"{API_BASE}/conversations/{selected_thread_id}",
                    timeout=15,
                )
                history_response.raise_for_status()
                messages = history_response.json()["messages"]
            except (requests.RequestException, ValueError, KeyError) as e:
                st.error(f"Could not load this conversation: {e}")

        for message in messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        if not selected_thread_id:
            st.caption("Start a new conversation to ask about your saved portfolio data.")
        elif prompt := st.chat_input("Ask about your portfolio"):
            try:
                response = requests.post(
                    f"{API_BASE}/ask",
                    json={"message": prompt, "thread_id": selected_thread_id},
                    timeout=120,
                )
                response.raise_for_status()
                response.json()["answer"]
            except requests.HTTPError as e:
                api_response = e.response
                if api_response is None:
                    st.error(f"API request failed: {e}")
                else:
                    try:
                        detail = api_response.json().get("detail", api_response.text)
                    except ValueError:
                        detail = api_response.text
                    st.error(f"API error ({api_response.status_code}): {detail}")
            except (requests.RequestException, ValueError, KeyError) as e:
                st.error(f"Could not complete the chat request: {e}")

with tab_market:
    st.caption("Yahoo Finance pricing for the configured instrument watchlist.")
    try:
        response = requests.get(f"{API_BASE}/market/watchlist", timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, KeyError) as exc:
        st.error(f"Could not load market watchlist: {exc}")
        payload = {"watchlist": []}

    rows = []
    for item in payload.get("watchlist", []):
        quote = item.get("quote") or {}
        forecast = item.get("forecast") or {}
        rows.append(
            {
                "Name": item.get("name"),
                "Ticker": item.get("ticker") or "—",
                "ISIN": item.get("isin") or "—",
                "Asset": item.get("asset_type") or "—",
                "Price": quote.get("price"),
                "Currency": quote.get("currency") or item.get("currency") or "—",
                "Day change %": quote.get("day_change_pct"),
                "Forecast 30d %": forecast.get("expected_return_pct"),
                "Signal": forecast.get("signal") or "—",
                "Status": item.get("status", "ok"),
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.info("No watchlist instruments are configured yet.")
          else:
                st.rerun()
