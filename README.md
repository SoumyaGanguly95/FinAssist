# FinAssist — Personal Financial Intelligence Platform

A hands-on learning project for **LangChain 1.0 / LangGraph**, **FastAPI**, and **Azure** — built by ingesting and reasoning over real personal investment data (Trade Republic, Scalable Capital, WisdomTree). Working end-to-end locally as of this writing: CSV/PDF ingestion through a LangChain parsing agent, human-reviewed commit to SQLite, and a LangGraph tool-calling insight agent, all served via FastAPI with a Streamlit client.

---

## 1. Scope & philosophy

The long-term vision is an enterprise platform (multi-tenant, live market feeds, tax optimization, alerting). This project is deliberately scoped as a **single-tenant MVP**, built **API-first** so the same core logic can later be triggered by a CLI, a Streamlit UI, or an Azure Function — only the entry point changes, never the business logic underneath it.

**Primary learning focus:** LangChain/LangGraph agent design.
**Secondary:** Azure deployment (planned, not yet done).
**Design principles carried through every phase:**
1. No fabricated or auto-committed financial data — every agent output is reviewed before it's persisted.
2. Business logic never lives inside the UI layer (`dashboard.py`) or the API layer (`app.py`) — both are thin entry points over plain functions in `ingest.py`/`agents.py`.
3. Everything is written cloud-agnostic first (DB-agnostic models, env-driven config) so moving to Azure is a deployment step, not a rewrite.

---

## 2. Project structure

```
finassist/
├── README.md
├── requirements.txt
├── Dockerfile          # builds app.py for Azure Container Apps (Phase 3, not yet deployed)
├── .env.example
├── .gitignore
├── schemas.py            # Pydantic: validates LLM output before it can become a DB row
├── models.py               # SQLAlchemy models + DB session (SQLite locally, swaps to Azure SQL via DATABASE_URL)
├── agents.py                 # ALL agent logic: parsing agent + insight agent + its tools
├── ingest.py                   # extract_text() + ingest_statement() (parse) + commit_parsed_statement() (save)
├── app.py                        # FastAPI service: /ingest, /ingest/commit, /ask, /health
├── dashboard.py                    # thin Streamlit client — calls the API, contains no logic
├── scripts/
│   ├── init_db.py                    # one-time/idempotent: creates SQLite tables
│   └── cli_ingest.py                   # fastest local loop: test ingestion without API/UI
├── tests/
│   └── test_agents.py                    # schema-level tests (expand as agent behavior stabilizes)
└── data/raw/                                # local dev only, gitignored — statements live here
```

Six files at the root carry all real logic. No deep package nesting — this was simplified from an earlier `src/finassist/{ingestion,agents,db,api}/` layout that added structure without adding clarity at this project's size.

---

## 3. Logic flow

### Flow 1 — Ingest a statement (CSV or PDF)

```
Client (dashboard.py or cli_ingest.py)
        │  upload/file path
        ▼
app.py  POST /ingest
        │  saves raw file to data/raw/ FIRST (audit trail, regardless of parse outcome)
        ▼
ingest.py  extract_text()
        │  PDF → pdfplumber text extraction
        │  CSV → read as raw text (LLM interprets it — see §5 note on efficiency)
        ▼
agents.py  parse_statement_text()
        │  create_agent(model=..., response_format=ParsedStatement)
        │  single-pass structured extraction — NO tool loop, no multi-step reasoning
        ▼
schemas.py  ParsedStatement / Transaction validation
        │  malformed or incomplete LLM output is rejected HERE, before it can
        │  reach the database
        ▼
Returned to the client — NOT saved yet
        │
        ▼
[ HUMAN REVIEWS THE OUTPUT ]  ← the actual review step; nothing auto-commits
        │  confirm (--commit flag, or "Confirm and save" button)
        ▼
app.py  POST /ingest/commit
        ▼
ingest.py  commit_parsed_statement()
        │  for each transaction: content_hash() checked against models.py
        │  → existing hash = skipped (dedup), new hash = inserted
        ▼
models.py  → SQLite (data/finassist.db)
```

### Flow 2 — Ask a question

```
Client (dashboard.py "Ask" tab)
        │  question text
        ▼
app.py  GET /ask
        ▼
agents.py  run_insight_query()
        │  create_agent(model=..., tools=[query_holdings, get_portfolio_valuation, flag_anomaly])
        │  THIS is where LangGraph's loop actually runs: the model decides
        │  which tool(s) to call, inspects the result, decides again if needed
        ▼
tools query models.py directly (SQLAlchemy) — the agent never sees raw SQL,
only what each tool function returns as a string
        ▼
Final assistant message → returned as the answer
```

**Why two different agent patterns:** the parsing agent needs zero reasoning — text in, structured data out, so a single `response_format` call is enough. The insight agent genuinely doesn't know in advance which data it needs, so it needs the tool-calling loop. Using the heavier pattern for both would be over-engineering the parsing side; using the lighter pattern for insight would make it unable to actually answer varied questions.

---

## 4. Setup

```bash
git clone <repo-url> && cd finassist
uv init --name finassist --python 3.12
uv add langchain langchain-openai langgraph fastapi "uvicorn[standard]" pydantic sqlalchemy pdfplumber yfinance streamlit requests python-dotenv
uv add --dev pytest ruff

cp .env.example .env
# fill in OPENAI_API_KEY (from platform.openai.com — separate from any ChatGPT subscription)

uv run python scripts/init_db.py

# Terminal 1
uv run uvicorn app:app --reload

# Terminal 2
uv run streamlit run dashboard.py
```

Fast local iteration loop (no API/UI needed) while tuning the parsing prompt:
```bash
uv run python scripts/cli_ingest.py data/raw/statement.csv --account "Trade Republic"
# review the printed JSON carefully, THEN:
uv run python scripts/cli_ingest.py data/raw/statement.csv --account "Trade Republic" --commit
```

---

## 5. Known limitations / lessons learned (kept honest, for future reference)

- **CSV is routed through the LLM parsing agent**, same as PDF. This works but is inefficient — CSV is already structured data, so paying LLM tokens to re-structure it is wasted cost and a source of misclassification risk. **TODO:** replace with a deterministic pandas-based CSV loader once the actual broker column layouts are known; reserve the LLM path for PDFs where layout genuinely needs interpretation.
- **`asset_class` classification needed a prompt fix** — the agent initially classified ETF purchases as `"other"` despite the statement text saying "UCITS ETF" explicitly. Fixed by making the classification rule in `PARSING_SYSTEM_PROMPT` explicit and example-driven rather than assuming the model would infer it. General lesson: don't assume correct classification from context — spell out the rule.
- **`Transaction.account_name` was a schema design bug**, not a prompt problem — it asked the LLM for a field that was redundant with `ParsedStatement.account_name` and was never actually read downstream. Removed entirely rather than prompted around. General lesson: a structured-output validation failure is worth checking against the schema itself before assuming it's a prompt/model problem.
- **No Alembic migrations yet** — `models.py`'s `init_db()` uses `create_all()`, fine for MVP, not safe for schema changes against real persisted data.
- **Model provider strings need re-verification before each session** — LangChain's model integration strings (`"openai:..."` vs `"azure_openai:..."`) and provider requirements (e.g. Azure requiring `OPENAI_API_VERSION`) change with library updates; don't assume last session's working string is still correct after an upgrade.

---

## 6. Roadmap

- [x] Phase 0/1 — Schema, ingestion pipeline, parsing + insight agents, FastAPI + Streamlit — **working locally**
- [ ] Phase 2 — Portfolio engine (valuation, P&L, allocation), deterministic CSV loader
- [ ] Phase 3 — Azure deployment (Container Apps, Blob Storage, Key Vault, Azure SQL)
- [ ] Phase 4 — Alembic migrations, expanded test coverage
- [ ] Phase 5 (stretch) — Forecasting (Prophet/LightGBM), multi-tenancy, alerting

## 7. Cost notes (see full breakdown discussed separately)

Local development is free (SQLite, OpenAI API pay-per-token only). Azure deployment, once reached, is estimated at roughly $5–15/month for this MVP's scale (Container Apps free tier covers request volume; Azure SQL Basic tier ~$5/month; token costs are the main variable, minimal at personal-project usage levels). Always set a spending cap/budget alert on both OpenAI and Azure before deploying.