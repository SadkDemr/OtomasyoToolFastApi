import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, testcasegen_service as svc


class _FakeUser:
    id = 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    return TestClient(app)


def _session_with_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_index": 0, "text": "Odeme onaylanir"},
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
