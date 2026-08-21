import asyncio
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
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        return _FakeResponse({"embedding": [0.1, 0.2, 0.3]})


def test_ollama_embed_returns_embedding_list(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    result = asyncio.run(ai_service.ollama_embed("bir metin"))
    assert result == [0.1, 0.2, 0.3]


def test_ollama_embed_uses_configured_model(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse({"embedding": [0.5]})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(ai_service, "get_embedding_config", lambda: {
        "url": "http://localhost:11434/api/embeddings", "model": "nomic-embed-text",
    })
    asyncio.run(ai_service.ollama_embed("metin"))
    assert captured["json"]["model"] == "nomic-embed-text"
    assert captured["json"]["prompt"] == "metin"


def test_ollama_embed_returns_none_on_connection_error(monkeypatch):
    class FailingClient(_FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("baglanti yok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    result = asyncio.run(ai_service.ollama_embed("metin"))
    assert result is None


def test_ollama_embed_returns_none_on_http_error(monkeypatch):
    class ErrorResponse(_FakeResponse):
        def raise_for_status(self):
            raise httpx.HTTPStatusError("model yok", request=None, response=None)

    class ErrorClient(_FakeAsyncClient):
        async def post(self, url, json):
            return ErrorResponse({})

    monkeypatch.setattr(httpx, "AsyncClient", ErrorClient)
    result = asyncio.run(ai_service.ollama_embed("metin"))
    assert result is None
