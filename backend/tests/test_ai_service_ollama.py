import asyncio
import json as json_lib
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


def test_ollama_generate_text_uses_small_default_num_ctx(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["json"] = json
            return _FakeResponse({"response": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    asyncio.run(ai_service.ollama_generate_text("prompt"))
    assert captured["json"]["options"]["num_ctx"] == ai_service.OLLAMA_NUM_CTX_DEFAULT
    assert ai_service.OLLAMA_NUM_CTX_DEFAULT < ai_service.OLLAMA_NUM_CTX_LARGE


def test_ollama_generate_text_respects_num_ctx_override(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["json"] = json
            return _FakeResponse({"response": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    asyncio.run(ai_service.ollama_generate_text("prompt", num_ctx=ai_service.OLLAMA_NUM_CTX_LARGE))
    assert captured["json"]["options"]["num_ctx"] == ai_service.OLLAMA_NUM_CTX_LARGE


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


class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeStreamClient(_FakeAsyncClient):
    def stream(self, method, url, json=None):
        self.sent_json = json
        self.sent_url = url
        return _FakeStreamCtx(_FakeStreamResponse([
            json_lib.dumps({"response": "Mer", "done": False}),
            json_lib.dumps({"response": "haba", "done": False}),
            json_lib.dumps({"response": "", "done": True}),
        ]))


class _FailingStreamClient(_FakeAsyncClient):
    def stream(self, method, url, json=None):
        raise httpx.ConnectError("baglanti yok", request=httpx.Request("POST", url))


async def _collect(agen):
    return [piece async for piece in agen]


def test_ollama_generate_text_stream_yields_chunks_in_order(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeStreamClient)
    pieces = asyncio.run(_collect(ai_service.ollama_generate_text_stream("bir prompt")))
    assert pieces == ["Mer", "haba"]


def test_ollama_generate_text_stream_sends_stream_true_and_model(monkeypatch):
    captured_client = {}

    class RecordingStreamClient(_FakeStreamClient):
        def stream(self, method, url, json=None):
            captured_client["json"] = json
            return super().stream(method, url, json=json)

    monkeypatch.setattr(httpx, "AsyncClient", RecordingStreamClient)
    monkeypatch.setattr(ai_service, "get_ollama_config", lambda: {
        "url": "http://localhost:11434/api/generate", "model": "gemma3:4b",
    })
    asyncio.run(_collect(ai_service.ollama_generate_text_stream("prompt")))
    assert captured_client["json"]["model"] == "gemma3:4b"
    assert captured_client["json"]["prompt"] == "prompt"
    assert captured_client["json"]["stream"] is True


def test_ollama_generate_text_stream_propagates_connection_error(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FailingStreamClient)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(_collect(ai_service.ollama_generate_text_stream("prompt")))
