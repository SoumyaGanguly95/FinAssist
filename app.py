"""
FastAPI service — the web service boundary. This runs on Azure Container Apps.
dashboard.py is a client of this API, not a container for this logic.

Run locally:
    uv run uvicorn app:app --reload
"""

from __future__ import annotations

import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile

from agents import run_insight_query
from ingest import commit_parsed_statement, ingest_statement
from models import init_db
from schemas import ParsedStatement


RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()  # MVP only — use Alembic migrations before real production data
    yield
    # Shutdown (optional cleanup)
    # e.g., close DB connections, release resources


app = FastAPI(
    title="FinAssist API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/ingest")
async def ingest(file: UploadFile, account_hint: str | None = None) -> dict:
    """
    Parses a statement and returns it for review — does NOT save it.
    Call /ingest/commit with the same source_file to actually persist it.
    """
    suffix = Path(file.filename).suffix
    saved_path = RAW_DATA_DIR / f"{uuid.uuid4().hex}{suffix}"
    saved_path.write_bytes(await file.read())

    try:
        parsed = ingest_statement(str(saved_path), account_hint=account_hint)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"parsed": parsed, "source_file": str(saved_path)}


@app.post("/ingest/commit")
async def commit(parsed: ParsedStatement, source_file: str):
    """
    Explicit save step, called after the client has reviewed /ingest's
    response and confirms it's correct.
    """
    return commit_parsed_statement(parsed, source_file=source_file)


@app.get("/ask")
async def ask(question: str):
    return {"question": question, "answer": run_insight_query(question)}


@app.get("/health")
async def health():
    return {"status": "ok"}
