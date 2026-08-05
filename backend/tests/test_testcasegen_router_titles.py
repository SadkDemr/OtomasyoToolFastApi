import io
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, testcasegen_service as svc


class _FakeUser:
    id = 1
    username = "tester"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    return TestClient(app)


def _session_with_one_screen(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"fake-png"), "image/png"))]
    session = client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files).json()
    return session


def test_extract_titles_streams_sse_and_persists_titles(client, monkeypatch):
    async def fake_vision(prompt, images_b64, model=None, timeout=90.0):
        return '{"screen_titles": [{"screen_index": 0, "candidate_titles": ["Baslik A"], "screen_summary": "ozet"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)
    session = _session_with_one_screen(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 200
    assert "screen_done" in resp.text
    assert "Baslik A" in resp.text
    assert "complete" in resp.text

    updated = client.get(f"/api/testcasegen/sessions/{session['id']}").json()
    assert updated["screens"][0]["candidate_titles"] == ["Baslik A"]
    assert updated["screens"][0]["parse_error"] is False


def test_extract_titles_marks_parse_error_on_invalid_json(client, monkeypatch):
    async def fake_vision(prompt, images_b64, model=None, timeout=90.0):
        return "bu JSON degil, ham metin"

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)
    session = _session_with_one_screen(client)

    client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    updated = client.get(f"/api/testcasegen/sessions/{session['id']}").json()
    assert updated["screens"][0]["parse_error"] is True
    assert updated["screens"][0]["screen_summary"] == "bu JSON degil, ham metin"


def test_extract_titles_without_screens_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 400


def test_extract_titles_reports_ollama_error_via_sse(client, monkeypatch):
    async def failing_vision(prompt, images_b64, model=None, timeout=90.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_vision", failing_vision)
    session = _session_with_one_screen(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 200
    assert "event: error" in resp.text


def test_extract_titles_marks_parse_error_on_malformed_json_shape(client, monkeypatch):
    raw_text = '{"screen_titles": "not-a-list"}'

    async def fake_vision(prompt, images_b64, model=None, timeout=90.0):
        return raw_text

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)
    session = _session_with_one_screen(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 200
    assert "event: error" not in resp.text
    assert "complete" in resp.text

    updated = client.get(f"/api/testcasegen/sessions/{session['id']}").json()
    assert updated["screens"][0]["parse_error"] is True
    assert updated["screens"][0]["candidate_titles"] == []
    assert updated["screens"][0]["screen_summary"] == raw_text


def test_add_edit_delete_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0], "text": "Elle eklenen baslik"},
    )
    assert resp.status_code == 200
    title_id = resp.json()["titles"][0]["id"]
    assert resp.json()["titles"][0]["screen_indices"] == [0]

    resp2 = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}",
        json={"text": "Guncellenmis baslik"},
    )
    assert resp2.json()["titles"][0]["text"] == "Guncellenmis baslik"

    resp3 = client.delete(f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}")
    assert resp3.json()["titles"] == []


def test_add_title_with_multiple_screen_indices(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0, 1, 2], "text": "Kar Payı Hesaplama Akışı"},
    )
    assert resp.status_code == 200
    assert resp.json()["titles"][0]["screen_indices"] == [0, 1, 2]


def test_add_title_with_empty_screen_indices_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [], "text": "Baslik"},
    )
    assert resp.status_code == 400
