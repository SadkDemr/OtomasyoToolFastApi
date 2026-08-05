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
        json={"screen_indices": [0], "text": "Tutar girilip onaylanır"},
    ).json()
    return session


def test_prioritize_assigns_score_level_and_rationale(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "Bu ekran doğrudan bir ödeme onayı içerdiği için yüksek öncelikli."

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize")
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] in ("high", "medium", "low")
    assert title["level_source"] == "rule"
    assert "yüksek öncelikli" in title["rationale"]


def test_prioritize_falls_back_to_generic_rationale_on_ollama_failure(client, monkeypatch):
    async def failing_text(prompt, model=None, timeout=60.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_text)
    session = _session_with_title(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize")
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] in ("high", "medium", "low")  # skor yine hesaplanir
    assert title["rationale"]  # bos degil, generic mesaj var


def test_manual_priority_override_sets_level_source_manual(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "gerekce"

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    session = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize").json()
    title_id = session["titles"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}/priority",
        json={"level": "low"},
    )
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] == "low"
    assert title["level_source"] == "manual"


def test_reprioritize_does_not_overwrite_manual_override(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "gerekce"

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0], "text": "Tutar girilip onaylanır"},
    ).json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0], "text": "SSS ekranı görüntülenir"},
    ).json()

    session = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize").json()
    manual_title_id = session["titles"][0]["id"]
    other_title_id = session["titles"][1]["id"]

    session = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{manual_title_id}/priority",
        json={"level": "low"},
    ).json()

    # Ikinci kez onceliklendirme calistir — manuel ayarlanan basligi ezmemeli
    session = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize").json()

    manual_title = next(t for t in session["titles"] if t["id"] == manual_title_id)
    other_title = next(t for t in session["titles"] if t["id"] == other_title_id)

    assert manual_title["level"] == "low"
    assert manual_title["level_source"] == "manual"
    assert other_title["level_source"] == "rule"


def test_prioritize_combines_notes_from_all_flow_screens(client, monkeypatch):
    captured = {}
    original_score_title = svc.score_title

    def spy_score_title(text, screen_note, screen_index):
        captured["screen_note"] = screen_note
        captured["screen_index"] = screen_index
        return original_score_title(text, screen_note, screen_index)

    async def fake_text(prompt, model=None, timeout=60.0):
        return "gerekce"

    monkeypatch.setattr(svc, "score_title", spy_score_title)
    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    session = client.post("/api/testcasegen/sessions").json()
    session_id = session["id"]
    svc.add_screen(1, session_id, b"a", note="ilk ekran notu")
    svc.add_screen(1, session_id, b"b", note="ikinci ekran notu")

    client.post(
        f"/api/testcasegen/sessions/{session_id}/titles",
        json={"screen_indices": [0, 1], "text": "Akis basligi"},
    )

    resp = client.post(f"/api/testcasegen/sessions/{session_id}/prioritize")
    assert resp.status_code == 200
    assert "ilk ekran notu" in captured["screen_note"]
    assert "ikinci ekran notu" in captured["screen_note"]
    assert captured["screen_index"] == 1  # screen_indices[-1] kullanilir


def test_manual_priority_rejects_invalid_level(client):
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}/priority",
        json={"level": "urgent"},
    )
    assert resp.status_code == 422
