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
from uuid import UUID

from fastapi import FastAPI, HTTPException, UploadFile
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update

from agents import get_insight_conversation, run_insight_query
from config import CHECKPOINT_DATABASE_PATH
from ingest import commit_parsed_statement, ingest_statement
from models import Conversation, get_session, init_db
from schemas import ParsedStatement


RAW_DATA_DIR = Path("data/raw")
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DB_PATH = Path(CHECKPOINT_DATABASE_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # MVP only — use Alembic migrations before real production data
    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        checkpointer.setup()
        app.state.checkpointer = checkpointer
        yield


app = FastAPI(
    title="FinAssist API",
    version="0.1.0",
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: UUID

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank")
        return value


@app.post("/conversations", status_code=201)
def create_conversation() -> dict:
    thread_id = str(uuid.uuid4())
    with get_session() as session:
        conversation = Conversation(thread_id=thread_id)
        session.add(conversation)
        session.flush()
        return {
            "thread_id": conversation.thread_id,
            "title": conversation.title,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }


@app.get("/conversations")
def list_conversations() -> dict:
    with get_session() as session:
        conversations = session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc())
        ).scalars().all()
        return {
            "conversations": [
                {
                    "thread_id": conversation.thread_id,
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                }
                for conversation in conversations
            ]
        }


@app.get("/conversations/{thread_id}")
def read_conversation(thread_id: UUID) -> dict:
    thread_id = str(thread_id)
    with get_session() as session:
        conversation = session.get(Conversation, thread_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        title = conversation.title

    messages = get_insight_conversation(thread_id, app.state.checkpointer)
    return {"thread_id": thread_id, "title": title, "messages": messages}


@app.post("/ingest")
def ingest(file: UploadFile, account_hint: str | None = None) -> dict:
    """
    Parses a statement and returns it for review — does NOT save it.
    Call /ingest/commit with the same source_file to actually persist it.
    """
    suffix = Path(file.filename).suffix
    saved_path = RAW_DATA_DIR / f"{uuid.uuid4().hex}{suffix}"
    saved_path.write_bytes(file.file.read())

    try:
        parsed = ingest_statement(str(saved_path), account_hint=account_hint)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Unable to parse statement: {e}") from e

    return {"parsed": parsed, "source_file": str(saved_path)}


@app.post("/ingest/commit")
def commit(parsed: ParsedStatement, source_file: str):
    """
    Explicit save step, called after the client has reviewed /ingest's
    response and confirms it's correct.
    """
    return commit_parsed_statement(parsed, source_file=source_file)


@app.post("/ask")
def ask(payload: ChatRequest):
    thread_id = str(payload.thread_id)
    with get_session() as session:
        conversation = session.get(Conversation, thread_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        is_new = conversation.title == "New conversation"

    answer = run_insight_query(
        message=payload.message,
        thread_id=thread_id,
        checkpointer=app.state.checkpointer,
    )

    with get_session() as session:
        values = {"updated_at": func.now()}
        if is_new:
            values["title"] = payload.message[:120]
        session.execute(
            update(Conversation)
            .where(Conversation.thread_id == thread_id)
            .values(**values)
        )

    return {
        "thread_id": thread_id,
        "answer": answer,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
