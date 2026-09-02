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
    assert add_resp.json() == {"status": "ok", "chunks": 1}

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
