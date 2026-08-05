import io

import openpyxl
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


def _session_with_generated_testcase(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tiklanir", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_indices": [0], "text": "Baslik"},
    ).json()
    title_id = session["titles"][0]["id"]
    gen = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    return session["id"], gen["testcases"][0]["id"]


def test_export_returns_valid_xlsx(client, monkeypatch):
    session_id, tc_id = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(f"/api/testcasegen/sessions/{session_id}/export", json={"testcase_ids": [tc_id]})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    assert ws[1][0].value == "ID"
    assert ws[2][2].value == "Baslik"


def test_export_no_testcase_ids_returns_400(client, monkeypatch):
    session_id, _ = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(f"/api/testcasegen/sessions/{session_id}/export", json={"testcase_ids": []})
    assert resp.status_code == 400
