# FinAssist

**A human-reviewed financial statement ingestion and portfolio Q&A application.**

FinAssist is a single-user personal-finance project for extracting transactions and reported positions from investment statements, reviewing the extracted data, and asking questions about records that have been saved. It combines a FastAPI service, a Streamlit client, SQLAlchemy persistence, and LangChain/LangGraph workflows.

> **Current scope:** Statement extraction, human review, record persistence, chat over saved records, and a configurable market watchlist with Yahoo Finance pricing are implemented. A lightweight statistical forecast layer for selected instruments is included as a non-advisory exploratory feature; it is not a broker feed, alpha model, or individualized financial recommendation.
>
> **Financial-data and security notice:** This is an educational project, not financial advice or a production-ready financial service. Model output may be inaccurate and must be checked against the source statement or upstream market feed. The application has no authentication or authorization. Uploaded files and database records are stored locally by default. Do not expose the service publicly or use it with sensitive financial data without adding the security, privacy, and operational controls described below.

## At a glance

| | |
|---|---|
| **Application** | FastAPI backend with a Streamlit web client |
| **AI workflows** | OpenAI-backed structured statement extraction and a LangGraph tool-calling insight agent |
| **Input formats** | PDF and CSV |
| **Persistence** | SQLAlchemy models; SQLite by default; separate SQLite checkpoint store for chat state |
| **Review model** | Parse first, allow edits, then explicitly confirm before saving records |
| **Runtime** | Python 3.13 or newer, managed with `uv` |

## Features

- Upload PDF and CSV investment statements from the Streamlit interface.
- Extract PDF text and tables with `pdfplumber`; send extracted text to an LLM for structured data extraction.
- Validate extracted transactions and position snapshots with Pydantic schemas.
- Review warnings and edit, add, or remove extracted rows before committing them.
- Save confirmed records with account and source-file references; use content hashes to skip duplicate transaction and position records.
- Chat with saved records through a LangGraph agent with narrowly defined tools for transaction search, position snapshots, and net cash flow.
- Monitor a configurable market watchlist with Yahoo Finance pricing and a simple 30-day directional forecast layer for selected instruments.
- Persist conversation metadata in the application database and conversational state in a separate SQLite checkpointer.
- Run statement ingestion from a command-line interface, either as a dry run or with an explicit `--commit`.

The statement parser and insight agent are **separate workflows**. The chat agent does not parse statements; it can query only records that have already been committed to the database.

### Configured market watchlist

The project now includes a default watchlist for the user's target instruments in `market.py`. Each item stores an ISIN and an optional Yahoo Finance ticker, with a subset marked as forecast-enabled for a simple directional 30-day estimate. This makes it easy to add or remove instruments without reworking the API or UI.

## Architecture

```text
┌─────────────────────┐       HTTP       ┌────────────────────────┐
│ Streamlit dashboard │ ────────────────> │ FastAPI service        │
│ upload, review, chat│                    │ routes and validation  │
│ + market watchlist  │                    │ + market endpoints     │
└─────────────────────┘                    └───────────┬────────────┘
                                                       │
                             ┌─────────────────────────┴────────────────────┐
                             │                                              │
                    Statement ingestion                              Portfolio chat
                             │                                              │
              pdfplumber → structured LLM extraction             LangGraph insight agent
                             │                                    ┌─────────┴─────────┐
                 Pydantic validation and warnings              transaction/position  checkpoint
                             │                                      tools             store
                   user review and confirmation                       │
                             └──────────────────┬─────────────────────┘
                                                │
                                    SQLAlchemy application database
                                                │
                                                ▼
                                    Yahoo Finance watchlist + simple trend model
```

### Main components

| File | Responsibility |
|---|---|
| `app.py` | FastAPI application, lifecycle initialization, request validation, and API routes. |
| `dashboard.py` | Streamlit UI for statement upload/review and portfolio conversations; communicates with the API over HTTP. |
| `ingest.py` | Extracts source text, invokes statement extraction, generates review warnings, and persists confirmed records. |
| `agents.py` | Defines structured statement extraction, database-backed insight tools, and the conversational LangGraph agent. |
| `schemas.py` | Pydantic statement, transaction, position, and enum definitions used to validate extracted and submitted data. |
| `verify.py` | Generates non-blocking warnings for source-text mismatches and, when balance data is present, inconsistent running balances. |
| `market.py` | Configurable watchlist of user instruments, Yahoo Finance quote fetcher, and a simple 30-day forecast estimator. |
| `models.py` | SQLAlchemy account, transaction, holding, and conversation models; engine/session setup and table initialization. |
| `config.py` | Loads environment settings, including database, checkpoint, dashboard API URLs, and watchlist defaults. |
| `normalize.py` | Experimental normalization utilities; not currently wired into the active ingestion path. |
| `prompt.txt` | Prompt artifact; the active extraction workflow currently defines its prompts in `agents.py`. |
| `scripts/cli_ingest.py` | Command-line wrapper for the shared parse-and-optional-commit workflow. |
| `scripts/init_db.py` | Initializes tables for the configured database. |
| `tests/` | Pytest coverage for agent helpers, database queries, checkpoint persistence, and conversation API routes. |
| `pyproject.toml` / `uv.lock` | Project metadata, dependency groups, and locked dependency versions. |
| `requirements.txt` | Exported runtime dependencies used by the API Docker image. |
| `Dockerfile` | Builds the API service image only; the Streamlit client runs separately. |

## How it works

### Statement ingestion and review

1. The dashboard uploads a PDF or CSV to `POST /ingest`. The API assigns a generated filename and saves the source under `data/raw/`.
2. `ingest.py` extracts PDF text and table rows using `pdfplumber`. CSV files are read as text; they are not currently parsed with a deterministic, broker-specific CSV importer.
3. The extracted text is sent to the structured extraction workflow in `agents.py`, which uses `openai:gpt-4.1-mini` and returns data shaped by the `ExtractDocument` schema.
4. Pydantic validates the extracted records. `verify.py` checks whether descriptions appear in the source text and may compare adjacent running balances when all transaction balances are available.
5. The API returns the parsed statement, review warnings, and source-file path. **This step does not persist the financial records.**
6. The user reviews and edits the transactions and positions in the dashboard.
7. On confirmation, the dashboard sends the edited statement to `POST /ingest/commit`. The ingestion service saves new records and skips records whose content hashes have already been stored.

Warnings are advisory: they do not prove that the extraction is correct, and they do not automatically change or reject the extracted values. Schema validation checks structure and types, not financial accuracy.

### Portfolio conversations

1. The client creates or selects a conversation identified by a UUID `thread_id`.
2. The client sends a non-blank message and thread ID to `POST /ask`.
3. The insight agent can use these database tools:
   - `query_transactions` searches imported transactions, with optional date, account, and partial instrument filters.
   - `query_positions` returns reported position snapshots, optionally filtered by account.
   - `get_net_cash_flow` sums recorded transaction amounts separately by currency.
4. The model uses tool results to compose a response. It is not given unrestricted SQL access.
5. LangGraph stores conversation state in the checkpoint database so a later message can continue the same thread.

The application stores statement-reported values, not live market data. Position values may be dated snapshots. Net cash flow is not portfolio value, investment return, or profit/loss. Amounts in different currencies are intentionally kept separate.

## Technology

- **Python 3.13+**
- **FastAPI** and **Uvicorn** for the HTTP API
- **Streamlit**, **Pandas**, and **Requests** for the dashboard
- **LangChain** and **LangGraph** for structured extraction and tool-calling conversations
- **OpenAI `gpt-4.1-mini`** through LangChain's model integration
- **Pydantic** for data contracts and validation
- **SQLAlchemy** with SQLite defaults for application data
- **LangGraph SQLite checkpointer** for conversational state
- **pdfplumber** for PDF text and table extraction
- **pytest** and **Ruff** in the development dependency group

## Requirements

- Python 3.13 or newer.
- [`uv`](https://docs.astral.sh/uv/) for dependency and environment management.
- An OpenAI API key for the LLM-backed parsing and chat workflows. API usage may incur provider charges.

The dashboard dependencies are an optional `dashboard` extra; pytest and other development utilities are in the `dev` dependency group. `uv.lock` records resolved versions. `requirements.txt` is an exported runtime dependency list for the API Docker image.

## Local setup

```bash
git clone <repository-url>
cd FinAssist

# Install the API, dashboard, and development dependencies.
uv sync --extra dashboard --group dev

# Create local configuration.
cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY` to your own key. Do not commit the real key.

The API initializes its tables on startup. To initialize them separately:

```bash
uv run python scripts/init_db.py
```

Start the API in one terminal:

```bash
uv run uvicorn app:app --reload
```

Start the dashboard in another terminal:

```bash
uv run streamlit run dashboard.py
```

By default, the API is available at `http://localhost:8000`, the interactive OpenAPI documentation at `http://localhost:8000/docs`, and the Streamlit dashboard at `http://localhost:8501`. Keep the API running while using the dashboard.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | Unset | Credential used by the OpenAI-backed extraction and chat workflows. Required for those workflows. |
| `DATABASE_URL` | `sqlite:///data/finassist.db` | SQLAlchemy URL for account, transaction, holding, and conversation metadata. SQLite is the local default. |
| `CHECKPOINT_DATABASE_PATH` | `data/finassist_checkpoints.sqlite` | SQLite file used by LangGraph to persist conversation state. |
| `FINASSIST_API_URL` | `http://localhost:8000` | API base URL used by the Streamlit dashboard. |

`config.py` loads a local `.env` file and honors variables already set in the process environment. The database, checkpoint, and uploaded files live under `data/` by default. They are local state and should be backed up only if needed; they should not be committed to source control.

## API reference

Interactive request/response schemas are available at `http://localhost:8000/docs` when the service is running.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingest` | Upload and parse a PDF/CSV statement. Returns parsed data for review; does not save financial records. Accepts an optional `account_hint`. |
| `POST` | `/ingest/commit` | Persist the user-confirmed `ParsedStatement`. Pass the source-file path as the `source_file` query parameter. |
| `POST` | `/conversations` | Create a conversation and return its thread ID. |
| `GET` | `/conversations` | List saved conversations, most recently updated first. |
| `GET` | `/conversations/{thread_id}` | Retrieve a conversation and its user-facing messages. |
| `POST` | `/ask` | Submit a message for an existing conversation. The JSON body contains `message` and `thread_id`. Messages must contain 1–4,000 non-whitespace characters; the thread ID must be a UUID. |
| `GET` | `/health` | Return the basic service status response. |

Example: upload a statement for parsing. The response includes the parsed data and the generated source-file path; it does not commit the records.

```bash
curl -X POST \
  -F "file=@path/to/statement.pdf" \
  "http://localhost:8000/ingest?account_hint=Broker"
```

Example conversation flow:

```bash
# Create a conversation and copy the returned thread_id.
curl -X POST "http://localhost:8000/conversations"

# Replace the UUID below with the returned thread_id.
curl -X POST "http://localhost:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"message":"Show my recent transactions","thread_id":"00000000-0000-0000-0000-000000000000"}'
```

## Command-line ingestion

The CLI uses the same `ingest_statement()` and `commit_parsed_statement()` functions as the API. Without `--commit`, it prints the parsed statement and warnings as a dry run:

```bash
uv run python scripts/cli_ingest.py path/to/statement.pdf --account "Broker name"
```

Review the output before explicitly saving it:

```bash
uv run python scripts/cli_ingest.py path/to/statement.pdf --account "Broker name" --commit
```

PDF and CSV are currently supported. Both formats use the same LLM extraction workflow; a deterministic importer for known CSV formats is a planned improvement.

## Docker

The Dockerfile builds the **FastAPI API only**. Build and run it locally with a configured `.env` file:

```bash
docker build -t finassist-api .
docker run --rm \
  -p 8000:8000 \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  finassist-api
```

The volume keeps the SQLite databases and uploaded statements outside the disposable container. Run the Streamlit dashboard separately and set `FINASSIST_API_URL` to the reachable API URL. For a hosted deployment, inject secrets through a secret manager rather than baking them into the image.

## Tests and development

Run the test suite with:

```bash
uv run pytest
```

The tests cover agent helpers and database queries, checkpoint history persistence, and conversation API behavior. The tests use fake models or patched calls for relevant agent paths; they do not measure extraction accuracy against a representative corpus of real-world statements.

After changing dependencies, update the lockfile with:

```bash
uv lock
```

Regenerate the API dependency export used by Docker with:

```bash
uv export --no-dev --format requirements-txt --no-hashes --output-file requirements.txt
```

## Data model and operational boundaries

- **Accounts** group imported financial records by account name.
- **Transactions** represent dated events such as buys, sells, fees, deposits, dividends, and withdrawals. Monetary amounts retain their recorded currency.
- **Holdings** represent reported position snapshots, not continuously updated prices.
- **Conversations** store metadata in the main database; LangGraph messages and agent state are stored in the separate checkpoint database.
- Transaction and holding records retain a source-file reference and use content hashes to detect duplicates.
- SQLAlchemy `create_all()` initializes missing tables; it is not a schema migration system.

The current application is single-user and unauthenticated. It does not enforce per-user access to conversations, statements, or records. A production deployment would require authentication and authorization, input and upload-size limits, secure secret management, database migrations, durable storage, backups, monitoring, and security testing. SQLite is suitable for local development but is not configured for concurrent multi-replica deployment. Azure deployment is not implemented; the Dockerfile is only an API container build.

## Limitations and responsible use

- CSV parsing uses an LLM rather than a deterministic broker-specific importer. This can add cost and introduce extraction errors.
- PDF text extraction may fail on scanned or image-only statements; OCR is not implemented.
- Review warnings are advisory. Pydantic validates data shape and types, not the financial truth of extracted values.
- The price layer is intentionally lightweight: it reads public Yahoo Finance quotes and computes a simple trend-based estimate for selected symbols, but it does not integrate broker feeds or portfolio-level valuation analytics.
- Imported position values are snapshots and may be stale. Net cash flow is a sum of recorded transaction amounts, not performance.
- The forecast layer is a statistical heuristic only. It is not live market data, not a guarantee of future returns, and not personalized financial advice.
- There is no multi-user authentication, authorization, or isolation.
- Uploaded statements are saved under `data/raw/`; this project does not provide a retention or deletion interface.
- Database tables are initialized with `create_all()` rather than managed migrations. Use Alembic and a reviewed migration process before evolving a production database.

Treat all model-generated financial data as unverified until compared with the original statement. Do not use the application as the sole basis for financial decisions.

## Roadmap

1. **Improve ingestion reliability:** build deterministic importers for known CSV formats; expand source reconciliation and tests over representative, sanitized statements.
2. **Build portfolio calculations:** establish reliable instrument identifiers and currency-aware position/transaction aggregation before presenting valuation or performance.
3. **Refine the predictive layer:** keep the watchlist configurable by ISIN/ticker, expand the forecast feature with clearer model diagnostics, and add a user-controlled selection of forecast-enabled instruments. Present uncertainty, data provenance, and out-of-sample limitations explicitly; this layer remains a decision-support tool, not a guarantee or personal recommendation.
4. **Production readiness:** add authentication/authorization, migrations, deployment-specific persistence and secrets, backups, monitoring, file-retention controls, and security controls before hosting sensitive data.

Any future forecast should be presented as an uncertain statistical estimate, not a promise or personalized financial advice. It should be compared with simple baselines on data not used to fit the model and communicate uncertainty and limitations clearly.

## Resume-ready project description

**FinAssist — Personal Finance Statement Intelligence**
*Python · FastAPI · Streamlit · LangChain · LangGraph · Pydantic · SQLAlchemy · SQLite*

> Built a full-stack personal-finance assistant that extracts transactions and position snapshots from PDF/CSV statements, supports human review before persistence, and answers natural-language questions over confirmed records.

Resume bullet points you can adapt:

- Built a FastAPI and Streamlit application for importing investment statements, editing extracted transactions and positions, and querying saved records through a conversational interface.
- Implemented an LLM-backed structured extraction pipeline with Pydantic contracts, PDF text/table extraction, source-evidence warnings, and an explicit human-confirmation step before financial data is persisted.
- Developed a LangGraph tool-calling agent with database-backed transaction search, position-snapshot lookup, and currency-separated net cash-flow queries; persisted conversation state with a SQLite checkpointer.
- Added SQLAlchemy persistence, content-hash duplicate detection, a reusable CLI ingestion workflow, Docker packaging for the API, and pytest coverage for query, checkpoint, and conversation behavior.

These bullets describe implemented functionality only. Add measured accuracy, latency, cost, or scale figures only after evaluating them with a documented test set. Before sharing this project publicly, use sanitized sample statements and screenshots, verify that no real financial records or credentials are tracked, and label any future roadmap work as planned rather than complete.
