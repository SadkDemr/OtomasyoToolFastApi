import asyncio
import json
import httpx
import pytest

from services import ai_service


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.sent_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        self.sent_json = json
        return _FakeResponse({"response": "merhaba"})


def test_ollama_generate_text_returns_response_field(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    result = asyncio.run(ai_service.ollama_generate_text("bir prompt"))
    assert result == "merhaba"


def test_ollama_generate_text_uses_configured_model(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse({"response": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(ai_service, "get_ollama_config", lambda: {
        "url": "http://localhost:11434/api/generate", "model": "gemma3:4b",
    })
    asyncio.run(ai_service.ollama_generate_text("prompt"))
    assert captured["json"]["model"] == "gemma3:4b"
    assert captured["json"]["prompt"] == "prompt"
    assert captured["json"]["stream"] is False
    assert "images" not in captured["json"]


def test_ollama_generate_vision_sends_images(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["json"] = json
            return _FakeResponse({"response": "gorsel yaniti"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    result = asyncio.run(ai_service.ollama_generate_vision("prompt", ["YmFzZTY0"]))
    assert result == "gorsel yaniti"
    assert captured["json"]["images"] == ["YmFzZTY0"]


def test_ollama_generate_text_propagates_connection_error(monkeypatch):
    class FailingClient(_FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("baglanti yok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(ai_service.ollama_generate_text("prompt"))
