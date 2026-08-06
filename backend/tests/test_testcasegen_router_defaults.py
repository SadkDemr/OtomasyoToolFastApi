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


@pytest.fixture
def client():
    # StaticPool: FastAPI's TestClient runs the ASGI app in a worker thread,
    # separate from this fixture's setup thread. The default SQLite in-memory
    # pool (SingletonThreadPool) is thread-scoped, so without StaticPool the
    # endpoint thread would see a fresh, table-less :memory: DB.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    user = User(username="tester", email="tester@example.com", hashed_password="x", full_name="Test Kullanici")
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_get_defaults_falls_back_to_full_name_and_design(client):
    resp = client.get("/api/testcasegen/defaults")
    assert resp.status_code == 200
    assert resp.json() == {"area_path": "", "assigned_to": "Test Kullanici", "state": "Design"}


def test_put_defaults_then_get_returns_saved_values(client):
    put_resp = client.put(
        "/api/testcasegen/defaults",
        json={"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"}

    get_resp = client.get("/api/testcasegen/defaults")
    assert get_resp.json() == {"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"}


def test_put_defaults_rejects_invalid_state(client):
    resp = client.put(
        "/api/testcasegen/defaults",
        json={"area_path": "", "assigned_to": "", "state": "GecersizDeger"},
    )
    assert resp.status_code == 422
