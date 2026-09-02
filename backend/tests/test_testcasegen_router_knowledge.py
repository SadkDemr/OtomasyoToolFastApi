import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models.db_models import User
from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestSession()


def _client_for(db, user):
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: (yield db)
    return TestClient(app)


def test_add_rule_requires_admin(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    assert resp.status_code == 403


def test_admin_can_add_list_and_delete_rule(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    add_resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    assert add_resp.status_code == 200
    assert add_resp.json() == {"status": "ok", "chunks": 1, "is_update": False, "diff_summary": None}

    list_resp = client.get("/api/testcasegen/knowledge/rules")
    rules = list_resp.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["title"] == "Kural"
    assert rules[0]["content"] == "Icerik"

    del_resp = client.delete(f"/api/testcasegen/knowledge/rules/{rules[0]['id']}")
    assert del_resp.status_code == 200
    assert client.get("/api/testcasegen/knowledge/rules").json()["rules"] == []


def test_add_rule_returns_503_when_embedding_unavailable(db_session, monkeypatch):
    async def fake_embed_fail(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_fail)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    assert resp.status_code == 503
    assert client.get("/api/testcasegen/knowledge/rules").json()["rules"] == []


def test_delete_unknown_rule_returns_404(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.delete("/api/testcasegen/knowledge/rules/999")
    assert resp.status_code == 404


def test_knowledge_status_reports_true_when_embedding_available(db_session, monkeypatch):
    async def fake_embed_ok(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_ok)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.get("/api/testcasegen/knowledge/status")
    assert resp.json() == {"embedding_model_available": True}


def test_knowledge_status_reports_false_when_embedding_unavailable(db_session, monkeypatch):
    async def fake_embed_fail(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_fail)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.get("/api/testcasegen/knowledge/status")
    assert resp.json() == {"embedding_model_available": False}


def test_knowledge_status_requires_admin(db_session, monkeypatch):
    async def fake_embed_ok(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_ok)

    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.get("/api/testcasegen/knowledge/status")
    assert resp.status_code == 403


def test_extract_file_txt_returns_text_and_suggested_title(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("sifre-kurali.txt", b"En az 8 karakter zorunlu.", "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "En az 8 karakter zorunlu."
    assert body["suggested_title"] == "sifre kurali"


def test_extract_file_rejects_unsupported_extension(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("kural.pdf", b"binary", "application/pdf")},
    )
    assert resp.status_code == 400


def test_extract_file_rejects_empty_text(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("bos.txt", b"   ", "text/plain")},
    )
    assert resp.status_code == 400


def test_extract_file_requires_admin(db_session):
    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("kural.txt", b"icerik", "text/plain")},
    )
    assert resp.status_code == 403


def test_add_rule_same_content_is_noop(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "chunks": 0, "is_update": False, "diff_summary": None}
    assert len(client.get("/api/testcasegen/knowledge/rules").json()["rules"]) == 1


def test_add_rule_update_replaces_content_and_returns_diff_summary(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Icerik 'eski' den 'yeni' ye degistirildi."

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "eski icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "yeni icerik"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_update"] is True
    assert body["diff_summary"] == "Icerik 'eski' den 'yeni' ye degistirildi."

    rules = client.get("/api/testcasegen/knowledge/rules").json()["rules"]
    assert len(rules) == 1
    assert rules[0]["content"] == "yeni icerik"


def test_add_rule_update_llm_failure_uses_fallback_message(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def failing_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        raise RuntimeError("Ollama'ya ulasilamadi")

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "eski icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "yeni icerik"})

    assert resp.status_code == 200
    assert "otomatik özet çıkarılamadı" in resp.json()["diff_summary"]


def test_add_example_and_list(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "adimlar"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "is_update": False, "diff_summary": None}

    examples = client.get("/api/testcasegen/knowledge/examples").json()["examples"]
    assert len(examples) == 1
    assert examples[0]["content"] == "adimlar"


def test_add_example_update_returns_diff_summary(db_session, monkeypatch):
    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Adim sirasi degisti."

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "eski adimlar"})
    resp = client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "yeni adimlar"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "is_update": True, "diff_summary": "Adim sirasi degisti."}
    examples = client.get("/api/testcasegen/knowledge/examples").json()["examples"]
    assert len(examples) == 1
    assert examples[0]["content"] == "yeni adimlar"
