"""
TestCaseGen - session_id path traversal / cross-tenant izolasyon regresyon testleri.

Whole-branch review Finding 1: session_id URL'den dogrudan Path birlestirmeye
gidiyordu, format dogrulamasi yoktu. Bu dosya iki seyi garanti eder:
  (a) bozuk/traversal session_id degerleri (".." , backslash icerenler, UUID
      olmayanlar) her yerde 404 dondurur ve dosya sistemine DATA_DIR disinda
      dokunmaz,
  (b) iki farkli kullanici birbirinin gecerli (UUID) oturumlarini okuyamaz/silemez.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import testcasegen_service as svc


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


def _make_client(tmp_path, monkeypatch, user_id: int = 1) -> TestClient:
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(user_id)
    return TestClient(app)


# session_id her zaman str(uuid.uuid4()) sekli olmali; asagidakilerin hicbiri
# gecerli bir UUID degil.
MALFORMED_SESSION_IDS = [
    "%2E%2E",              # url-encoded ".." — DATA_DIR/{uid}/.. -> DATA_DIR/{uid} parent
    "..",                   # duz traversal
    "a%5Cb",                # url-encoded backslash (Windows'ta path ayiraci)
    "not-a-valid-uuid",     # UUID olmayan rastgele metin
]


@pytest.mark.parametrize("bad_id", MALFORMED_SESSION_IDS)
def test_malformed_session_id_get_returns_404(tmp_path, monkeypatch, bad_id):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.get(f"/api/testcasegen/sessions/{bad_id}")
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_id", MALFORMED_SESSION_IDS)
def test_malformed_session_id_put_returns_404(tmp_path, monkeypatch, bad_id):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.put(f"/api/testcasegen/sessions/{bad_id}/screens/reorder", json={"order": []})
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_id", MALFORMED_SESSION_IDS)
def test_malformed_session_id_delete_returns_404(tmp_path, monkeypatch, bad_id):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.delete(f"/api/testcasegen/sessions/{bad_id}")
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_id", MALFORMED_SESSION_IDS)
def test_malformed_session_id_screen_image_returns_404(tmp_path, monkeypatch, bad_id):
    client = _make_client(tmp_path, monkeypatch)
    resp = client.get(f"/api/testcasegen/sessions/{bad_id}/screens/0/image")
    assert resp.status_code == 404


def test_traversal_delete_does_not_wipe_data_dir(tmp_path, monkeypatch):
    """DELETE /sessions/%2E%2E eskiden shutil.rmtree(DATA_DIR/{uid}/..) calistirip
    TUM testcasegen_data agacini siliyordu. Simdi 404 donmeli ve mevcut oturum
    (ve kullanici dizini) yerinde durmali."""
    client = _make_client(tmp_path, monkeypatch, user_id=1)
    session = client.post("/api/testcasegen/sessions").json()

    resp = client.delete("/api/testcasegen/sessions/%2E%2E")
    assert resp.status_code == 404

    # Kullanicinin dizini ve oturumu hala mevcut
    assert (tmp_path / "1").exists()
    resp2 = client.get(f"/api/testcasegen/sessions/{session['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == session["id"]


def test_backslash_traversal_cannot_reach_other_user_dir(tmp_path, monkeypatch):
    """Backslash Windows'ta path ayiracidir ama URL ayiracidir degildir; bu yuzden
    tek bir path segmenti icinde sunucuya ulasip Path() birlestirmesinde ayirac
    olarak yorumlanabilir. Format dogrulamasi bunu UUID olmadigi icin reddetmeli."""
    victim = _make_client(tmp_path, monkeypatch, user_id=1)
    victim_session = victim.post("/api/testcasegen/sessions").json()

    attacker = _make_client(tmp_path, monkeypatch, user_id=2)
    traversal_id = f"..\\1\\{victim_session['id']}"
    resp = attacker.get(f"/api/testcasegen/sessions/{traversal_id}")
    assert resp.status_code == 404


def test_cross_tenant_cannot_read_other_users_session(tmp_path, monkeypatch):
    user1 = _make_client(tmp_path, monkeypatch, user_id=1)
    session1 = user1.post("/api/testcasegen/sessions").json()

    user2 = _make_client(tmp_path, monkeypatch, user_id=2)
    resp = user2.get(f"/api/testcasegen/sessions/{session1['id']}")
    assert resp.status_code == 404


def test_cross_tenant_cannot_delete_other_users_session(tmp_path, monkeypatch):
    user1 = _make_client(tmp_path, monkeypatch, user_id=1)
    session1 = user1.post("/api/testcasegen/sessions").json()

    user2 = _make_client(tmp_path, monkeypatch, user_id=2)
    resp = user2.delete(f"/api/testcasegen/sessions/{session1['id']}")
    assert resp.status_code == 404

    # Kurban oturum hala user 1'in dizininde saglam durmali
    resp2 = user1.get(f"/api/testcasegen/sessions/{session1['id']}")
    assert resp2.status_code == 200


def test_cross_tenant_cannot_read_other_users_screen_image(tmp_path, monkeypatch):
    import io

    user1 = _make_client(tmp_path, monkeypatch, user_id=1)
    session1 = user1.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"gizli-veri"), "image/png"))]
    user1.post(f"/api/testcasegen/sessions/{session1['id']}/screens/upload", files=files)

    user2 = _make_client(tmp_path, monkeypatch, user_id=2)
    resp = user2.get(f"/api/testcasegen/sessions/{session1['id']}/screens/0/image")
    assert resp.status_code == 404
