import pytest

from services import testcasegen_service as svc


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    yield tmp_path


def test_create_session_returns_empty_session_with_id():
    session = svc.create_session(user_id=1)
    assert session["user_id"] == 1
    assert session["current_step"] == 1
    assert session["screens"] == []
    assert session["titles"] == []
    assert session["testcases"] == []
    assert "id" in session and len(session["id"]) > 0


def test_create_session_persists_to_disk():
    session = svc.create_session(user_id=1)
    loaded = svc.load_session(user_id=1, session_id=session["id"])
    assert loaded["id"] == session["id"]


def test_load_session_missing_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        svc.load_session(user_id=1, session_id="does-not-exist")


def test_list_sessions_returns_only_that_users_sessions():
    s1 = svc.create_session(user_id=1)
    svc.create_session(user_id=2)
    sessions = svc.list_sessions(user_id=1)
    assert [s["id"] for s in sessions] == [s1["id"]]


def test_delete_session_removes_it():
    session = svc.create_session(user_id=1)
    svc.delete_session(user_id=1, session_id=session["id"])
    with pytest.raises(FileNotFoundError):
        svc.load_session(user_id=1, session_id=session["id"])


def test_add_screen_appends_with_incrementing_index():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"fake-png-bytes-1", ext=".png", note="ilk ekran")
    session = svc.add_screen(1, session["id"], b"fake-png-bytes-2", ext=".png")
    assert [s["index"] for s in session["screens"]] == [0, 1]
    assert session["screens"][0]["user_note"] == "ilk ekran"
    img_path = svc.screen_image_path(1, session["id"], 0, ".png")
    assert img_path.read_bytes() == b"fake-png-bytes-1"


def test_reorder_screens_changes_order_and_reindexes():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="A")
    session = svc.add_screen(1, session["id"], b"b", note="B")
    session = svc.add_screen(1, session["id"], b"c", note="C")
    session = svc.reorder_screens(1, session["id"], order=[2, 0, 1])
    assert [s["user_note"] for s in session["screens"]] == ["C", "A", "B"]
    assert [s["index"] for s in session["screens"]] == [0, 1, 2]


def test_update_screen_note_changes_note_only():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="eski not")
    session = svc.update_screen_note(1, session["id"], index=0, note="yeni not")
    assert session["screens"][0]["user_note"] == "yeni not"


def test_delete_screen_removes_and_reindexes():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="A")
    session = svc.add_screen(1, session["id"], b"b", note="B")
    session = svc.delete_screen(1, session["id"], index=0)
    assert len(session["screens"]) == 1
    assert session["screens"][0]["user_note"] == "B"
    assert session["screens"][0]["index"] == 0
