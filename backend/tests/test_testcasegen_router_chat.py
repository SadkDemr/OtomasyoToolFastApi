import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, testcasegen_service as svc, knowledge_service


class _FakeUser:
    id = 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _parse_sse(text):
    """SSE gövdesini [(event, data), ...] listesine çevirir (frontend'deki parse mantığının aynısı)."""
    events = []
    for part in text.split("\n\n"):
        if not part.strip():
            continue
        evt = "log"
        data_lines = []
        for line in part.split("\n"):
            if line.startswith("event:"):
                evt = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        events.append((evt, "\n".join(data_lines)))
    return events


def test_chat_streams_tokens_and_completes(client, monkeypatch):
    async def fake_stream(prompt, model=None, timeout=300.0):
        for piece in ["Mer", "haba"]:
            yield piece

    monkeypatch.setattr(ai_service, "ollama_generate_text_stream", fake_stream)

    resp = client.post("/api/testcasegen/chat", json={"message": "Selam"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    tokens = [data for evt, data in events if evt == "token"]
    assert tokens == ["Mer", "haba"]
    assert events[-1][0] == "complete"


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/testcasegen/chat", json={"message": "   "})
    assert resp.status_code == 400


def test_chat_injects_knowledge_context(client, monkeypatch):
    captured = {}

    async def fake_stream(prompt, model=None, timeout=300.0):
        captured["prompt"] = prompt
        yield "cevap"

    async def fake_search(db, query_text, top_k=5, entry_types=None):
        return ["Sirket standardi: her ekran icin en az 1 negatif senaryo yazilmali"]

    monkeypatch.setattr(ai_service, "ollama_generate_text_stream", fake_stream)
    monkeypatch.setattr(knowledge_service, "search", fake_search)

    resp = client.post("/api/testcasegen/chat", json={"message": "Login ekrani nasil test edilir?"})
    assert resp.status_code == 200
    assert "negatif senaryo" in captured["prompt"]


def test_chat_continues_when_knowledge_search_fails(client, monkeypatch):
    async def fake_stream(prompt, model=None, timeout=300.0):
        yield "cevap"

    async def failing_search(db, query_text, top_k=5, entry_types=None):
        raise RuntimeError("db hatasi")

    monkeypatch.setattr(ai_service, "ollama_generate_text_stream", fake_stream)
    monkeypatch.setattr(knowledge_service, "search", failing_search)

    resp = client.post("/api/testcasegen/chat", json={"message": "Bir soru"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "complete"


def test_chat_sends_error_event_on_ollama_failure(client, monkeypatch):
    async def failing_stream(prompt, model=None, timeout=300.0):
        raise ConnectionError("ollama kapali")
        yield  # pragma: no cover - generator olması için gerekli, hiç çalışmaz

    monkeypatch.setattr(ai_service, "ollama_generate_text_stream", failing_stream)

    resp = client.post("/api/testcasegen/chat", json={"message": "Bir soru"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"


def test_chat_includes_conversation_history_in_prompt(client, monkeypatch):
    captured = {}

    async def fake_stream(prompt, model=None, timeout=300.0):
        captured["prompt"] = prompt
        yield "cevap"

    monkeypatch.setattr(ai_service, "ollama_generate_text_stream", fake_stream)

    resp = client.post("/api/testcasegen/chat", json={
        "message": "Peki sifre yanlissa?",
        "history": [
            {"role": "user", "content": "Login ekrani nasil test edilir?"},
            {"role": "assistant", "content": "Kullanici adi ve sifre girilir."},
        ],
    })
    assert resp.status_code == 200
    assert "Login ekrani nasil test edilir?" in captured["prompt"]
    assert "Kullanici adi ve sifre girilir." in captured["prompt"]
