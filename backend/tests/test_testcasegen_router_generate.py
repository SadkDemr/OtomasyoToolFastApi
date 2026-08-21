import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, knowledge_service, testcasegen_service as svc


class _FakeUser:
    id = 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)

    async def _default_ollama_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", _default_ollama_embed)

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


def _session_with_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0], "text": "Odeme onaylanir"},
    ).json()
    return session


def test_generate_testcases_creates_and_validates_steps(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return (
            '{"steps": [\n'
            '  {"step_action": "\\"Devam\\" butonuna tiklanir", "step_expected": "Onay ekrani acilir"},\n'
            '  {"step_action": "\\"Onayla\\" tikla", "step_expected": ""}\n'
            ']}'
        )

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 200
    testcases = resp.json()["testcases"]
    assert len(testcases) == 1
    steps = testcases[0]["steps"]
    assert steps[0]["violations"] == []
    assert len(steps[1]["violations"]) >= 1  # emir kipi + bos expected


def test_generate_testcases_unknown_title_id_is_skipped(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": []}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": ["bilinmeyen-id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["testcases"] == []


def test_generate_testcases_ollama_failure_returns_503(client, monkeypatch):
    async def failing_text(prompt, model=None, timeout=60.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 503


def test_generate_testcases_multi_screen_flow_includes_all_screens_in_prompt(client, monkeypatch):
    captured = {}

    async def fake_vision(prompt, images_b64, model=None, timeout=60.0):
        captured["prompt"] = prompt
        captured["images_b64"] = images_b64
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)

    session = client.post("/api/testcasegen/sessions").json()
    session_id = session["id"]
    for note in ("Login ekranı", "Diğer İşlemler ekranı", "Kar Payı Hesapla ekranı"):
        svc.add_screen(1, session_id, b"fake-png", note="")
    loaded = svc.load_session(1, session_id)
    summaries = ["Login ekranı görüntülenir", "Diğer İşlemler menüsü açılır", "Kar Payı Hesapla ekranı açılır"]
    for i, summary in enumerate(summaries):
        loaded["screens"][i]["screen_summary"] = summary
    svc.save_session(1, session_id, loaded)

    title = client.post(
        f"/api/testcasegen/sessions/{session_id}/titles",
        json={"screen_indices": [0, 1, 2], "text": "Kar Payı Hesaplama Akışı"},
    ).json()["titles"][0]

    resp = client.post(
        f"/api/testcasegen/sessions/{session_id}/generate-testcases",
        json={"title_ids": [title["id"]]},
    )
    assert resp.status_code == 200

    prompt = captured["prompt"]
    assert "Login ekranı görüntülenir" in prompt
    assert "Diğer İşlemler menüsü açılır" in prompt
    assert "Kar Payı Hesapla ekranı açılır" in prompt
    assert prompt.index(summaries[0]) < prompt.index(summaries[1]) < prompt.index(summaries[2])
    assert len(captured["images_b64"]) == 3  # her ekranin gercek goruntusu de gonderilmeli


def test_edit_step_revalidates(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tıkla", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]
    assert gen_resp["testcases"][0]["steps"][0]["violations"] != []

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tıklanır", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    updated_step = resp.json()["testcases"][0]["steps"][0]
    assert updated_step["violations"] == []


def test_edit_step_adds_correction_entry_when_changed(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tikla", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tıklanır", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "correction"
    assert "X tikla" in calls[0][2]
    assert "X tıklanır" in calls[0][2]


def test_edit_step_skips_correction_entry_when_unchanged(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tıklanır", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    assert calls == []
