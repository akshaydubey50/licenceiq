"""Offline query-rewrite adapter checks use the real SDK with mock HTTP."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import OpenAI

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.providers import openai_query_rewrite
from app.providers.openai_query_rewrite import OpenAIQueryRewriteProvider
from app.providers.query_rewrite import QueryRewriteRequest


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, OPENAI_API_KEY="test-key-not-a-credential", **overrides)


def request_context() -> QueryRewriteRequest:
    return QueryRewriteRequest(
        question="What about that one?",
        previous_questions=(
            "Are there any restrictions?",
            "Does it mention eyesight?",
        ),
    )


def response_body(
    payload: dict[str, Any] | None = None,
    *,
    status: str = "completed",
    refusal: bool = False,
) -> dict[str, Any]:
    result = payload or {
        "query": "driving licence eyesight restriction",
        "intent": "FOLLOW_UP",
    }
    part = (
        {"type": "refusal", "refusal": "Cannot rewrite"}
        if refusal
        else {"type": "output_text", "text": json.dumps(result), "annotations": []}
    )
    return {
        "id": "resp_rewrite_offline",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": [
            {
                "id": "msg_rewrite_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [part],
            }
        ],
    }


def mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> OpenAI:
        captured.update(kwargs)
        return OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)

    monkeypatch.setattr(openai_query_rewrite, "OpenAI", client)
    return captured


def test_request_uses_strict_schema_once_without_tools_or_document_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    client_args = mock_transport(monkeypatch, handler)
    result = OpenAIQueryRewriteProvider(settings()).rewrite(request_context(), timeout_seconds=5)
    assert result.query == "driving licence eyesight restriction"
    assert len(requests) == 1
    payload = requests[0]
    assert payload["store"] is False
    assert "tools" not in payload
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    assert client_args["timeout"] == 5
    assert client_args["max_retries"] == 0
    user_text = payload["input"][0]["content"][0]["text"]
    assert "What about that one?" in user_text
    assert "Are there any restrictions?" in user_text
    assert "document_id" not in user_text
    assert "blocks" not in user_text
    assert "citations" not in user_text
    assert '"answer"' not in user_text.casefold()


@pytest.mark.parametrize(
    "body",
    [
        response_body({"query": "", "intent": "FOLLOW_UP"}),
        response_body({"query": "valid", "intent": "UNKNOWN"}),
        response_body({"query": "valid", "intent": "LOOKUP", "answer": "invented"}),
        response_body(status="incomplete"),
        response_body(refusal=True),
    ],
)
def test_malformed_refused_or_incomplete_output_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
) -> None:
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ApplicationError) as error:
        OpenAIQueryRewriteProvider(settings()).rewrite(request_context())
    assert error.value.code == "QUESTION_PROVIDER_ERROR"


def test_timeout_is_sanitized_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("PRIVATE_REWRITE_DETAIL", request=request)

    client_args = mock_transport(monkeypatch, handler)
    with pytest.raises(ApplicationError) as error:
        OpenAIQueryRewriteProvider(settings()).rewrite(request_context(), timeout_seconds=100)
    assert error.value.code == "QUESTION_TIMEOUT"
    assert "PRIVATE_REWRITE_DETAIL" not in str(error.value)
    assert client_args["timeout"] == 8
    assert client_args["max_retries"] == 0
    assert calls == 1


def test_missing_key_does_not_create_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_client(**kwargs: Any) -> None:
        pytest.fail("Missing credentials must never create an SDK client")

    monkeypatch.setattr(openai_query_rewrite, "OpenAI", fail_client)
    provider = OpenAIQueryRewriteProvider(Settings(_env_file=None, OPENAI_API_KEY=""))
    with pytest.raises(ApplicationError) as error:
        provider.rewrite(request_context())
    assert error.value.code == "QUESTION_NOT_CONFIGURED"
