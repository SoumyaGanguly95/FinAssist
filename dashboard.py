"""
Streamlit client — thin by design. All logic lives in app.py/agents.py/
ingest.py; this file only makes HTTP calls and renders results.

Run (with the API running separately: uv run uvicorn app:app --reload):
    uv run streamlit run dashboard.py
"""

import os

import requests
import streamlit as st

API_BASE = os.environ.get("FINASSIST_API_URL", "http://localhost:8000")

st.set_page_config(page_title="FinAssist", layout="wide")
st.title("FinAssist")

tab_ingest, tab_ask = st.tabs(["Ingest statement", "Ask a question"])

with tab_ingest:
    uploaded = st.file_uploader("Upload a statement (PDF or CSV)", type=["pdf", "csv"])
    account_hint = st.text_input("Account (optional)", placeholder="e.g. Trade Republic")

    if uploaded and st.button("Parse"):
        with st.spinner("Parsing statement..."):
            resp = requests.post(
                f"{API_BASE}/ingest",
                files={"file": (uploaded.name, uploaded.getvalue())},
                params={"account_hint": account_hint} if account_hint else {},
            )
        if resp.ok:
            data = resp.json()
            st.session_state["last_parsed"] = data
            st.json(data["parsed"])
        else:
            st.error(resp.json().get("detail", "Parsing failed"))

    if "last_parsed" in st.session_state:
        st.divider()
        st.caption("Review the parsed result above, then confirm to save.")
        if st.button("Confirm and save to database"):
            data = st.session_state["last_parsed"]
            commit_resp = requests.post(
                f"{API_BASE}/ingest/commit",
                json=data["parsed"],
                params={"source_file": data["source_file"]},
            )
            if commit_resp.ok:
                st.success(commit_resp.json())
                del st.session_state["last_parsed"]
            else:
                st.error(commit_resp.text)

with tab_ask:
    question = st.text_input("Ask about your portfolio")
    if question and st.button("Ask"):
        with st.spinner("Thinking..."):
            resp = requests.get(f"{API_BASE}/ask", params={"question": question})
        if resp.ok:
            st.write(resp.json()["answer"])
        else:
            st.error(resp.text)