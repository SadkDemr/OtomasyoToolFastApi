import base64
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import testcasegen_service as svc


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


def test_create_and_get_session(client):
    resp = client.post("/api/testcasegen/sessions")
    assert resp.status_code == 200
    session = resp.json()
    assert session["screens"] == []

    resp2 = client.get(f"/api/testcasegen/sessions/{session['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == session["id"]


def test_get_missing_session_returns_404(client):
    resp = client.get("/api/testcasegen/sessions/does-not-exist")
    assert resp.status_code == 404


def test_list_sessions(client):
    client.post("/api/testcasegen/sessions")
    client.post("/api/testcasegen/sessions")
    resp = client.get("/api/testcasegen/sessions")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2


def test_delete_session(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.delete(f"/api/testcasegen/sessions/{session['id']}")
    assert resp.status_code == 200
    resp2 = client.get(f"/api/testcasegen/sessions/{session['id']}")
    assert resp2.status_code == 404


def test_upload_screens_multipart(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("screen1.png", io.BytesIO(b"fake-bytes"), "image/png"))]
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["screens"]) == 1


def test_capture_screen_from_base64(client):
    session = client.post("/api/testcasegen/sessions").json()
    b64 = base64.b64encode(b"fake-frame-bytes").decode()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/screens/capture",
        json={"image_b64": b64, "note": "ADB'den yakalandı"},
    )
    assert resp.status_code == 200
    screens = resp.json()["screens"]
    assert screens[0]["user_note"] == "ADB'den yakalandı"


def test_capture_screen_invalid_base64_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/screens/capture",
        json={"image_b64": "not-valid-base64!!"},
    )
    assert resp.status_code == 400


def test_reorder_screens(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)
    files = [("files", ("b.png", io.BytesIO(b"b"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/screens/reorder",
        json={"order": [1, 0]},
    )
    assert resp.status_code == 200
    assert resp.json()["screens"][0]["index"] == 0


def test_edit_screen_note(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/screens/0",
        json={"note": "güncellendi"},
    )
    assert resp.status_code == 200
    assert resp.json()["screens"][0]["user_note"] == "güncellendi"


def test_delete_screen(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.delete(f"/api/testcasegen/sessions/{session['id']}/screens/0")
    assert resp.status_code == 200
    assert resp.json()["screens"] == []
