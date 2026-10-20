import json
from unittest.mock import Mock

import httpx
import pytest
from app.config import settings
from app.llm.client import ModelUnavailableError, StructuredOutputError
from app.llm.llama_cpp import LlamaCppASLClient


def configured_client(monkeypatch, handler):
    monkeypatch.setattr(settings, "llm_mode", "neural")
    client = LlamaCppASLClient()
    monkeypatch.setattr(client, "load_model", lambda: True)
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return client


def test_local_cpu_requests_schema_and_disables_thinking(monkeypatch):
    def respond(request):
        assert request.url.host == "127.0.0.1"
        body = json.loads(request.content)
        assert body["chat_template_kwargs"]["enable_thinking"] is False
        assert body["response_format"]["schema"] == {"type":"object"}
        return httpx.Response(200, json={"choices":[{"finish_reason":"stop", "message":{"content":'{"ready":true}'}}]})
    client = configured_client(monkeypatch, respond)
    assert client.generate("prompt", {}, json_schema={"type":"object"}) == '{"ready":true}'
    assert client.get_status()["generation_verified"] is True


def test_truncated_cpu_response_is_rejected(monkeypatch):
    client = configured_client(monkeypatch, lambda request: httpx.Response(200, json={"choices":[{"finish_reason":"length", "message":{"content":"{ "}}]}))
    with pytest.raises(StructuredOutputError):
        client.generate("prompt", {})
    assert client.get_status()["generation_verified"] is False


def test_cpu_service_failure_never_returns_heuristic(monkeypatch):
    client = configured_client(monkeypatch, lambda request: httpx.Response(503, json={"error":"unavailable"}))
    with pytest.raises(ModelUnavailableError):
        client.generate("prompt", {"description":"المكيف لا يعمل"})
    assert client.get_status()["generation_verified"] is False


def test_exited_model_process_clears_readiness():
    client = LlamaCppASLClient()
    client._loaded = client._generation_verified = True
    client._process = Mock()
    client._process.poll.return_value = 1
    result = client.get_status()
    assert result["is_neural_loaded"] is False
    assert result["generation_verified"] is False
    assert result["error"] == "model_process_exited"
