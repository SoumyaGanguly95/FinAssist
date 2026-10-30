import app as api
import models
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_conversation_routes_create_resume_and_reject_unknown_thread(
    monkeypatch, tmp_path
):
    database_engine = create_engine(f"sqlite:///{tmp_path / 'app.sqlite'}")
    monkeypatch.setattr(models, "SessionLocal", sessionmaker(bind=database_engine))
    monkeypatch.setattr(
        api,
        "init_db",
        lambda: models.Base.metadata.create_all(database_engine),
    )
    monkeypatch.setattr(
        api,
        "CHECKPOINT_DB_PATH",
        tmp_path / "checkpoints.sqlite",
    )
    monkeypatch.setattr(
        api,
        "get_insight_conversation",
        lambda thread_id, checkpointer: [
            {"role": "user", "content": "Show recent activity"},
            {"role": "assistant", "content": "Here is your activity."},
        ],
    )
    calls = []

    def fake_run_insight_query(message, thread_id, checkpointer):
        calls.append((message, thread_id, checkpointer))
        return "Here is your activity."

    monkeypatch.setattr(api, "run_insight_query", fake_run_insight_query)

    with TestClient(api.app) as client:
        created = client.post("/conversations")
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]

        answer = client.post(
            "/ask",
            json={"message": "Show recent activity", "thread_id": thread_id},
        )
        assert answer.status_code == 200
        assert answer.json()["answer"] == "Here is your activity."
        assert calls[0][0:2] == ("Show recent activity", thread_id)
        assert calls[0][2] is not None

        history = client.get(f"/conversations/{thread_id}")
        assert history.status_code == 200
        assert history.json()["messages"][-1]["role"] == "assistant"

        listed = client.get("/conversations")
        assert listed.status_code == 200
        assert listed.json()["conversations"][0]["thread_id"] == thread_id
        assert listed.json()["conversations"][0]["title"] == "Show recent activity"

        unknown = client.post(
            "/ask",
            json={
                "message": "This thread does not exist",
                "thread_id": "c29a6e2b-5594-4420-b793-a421d77a8980",
            },
        )
        assert unknown.status_code == 404
