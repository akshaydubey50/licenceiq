"""Offline checks for the document-free local OpenAI OCR startup preflight."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import OpenAI

from app.core.config import Settings
from app.providers import openai_runtime
from app.providers.openai_runtime import OpenAIRuntimeCheckError, verify_openai_ocr_runtime


def settings(**overrides: Any) -> Settings:
    """Create isolated test settings without loading the ignored developer environment."""
    return Settings(_env_file=None, OPENAI_API_KEY="test-key-not-a-credential", **overrides)


def response_body(*, status: str = "completed") -> dict[str, Any]:
    """Return the minimum Responses envelope needed by the SDK parser."""
    return {
        "id": "resp_preflight",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": [],
    }


def mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> dict[str, Any]:
    """Replace only the SDK transport while preserving request serialization."""
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> OpenAI:
        captured.update(kwargs)
        return OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)

    monkeypatch.setattr(openai_runtime, "OpenAI", client)
    return captured


def test_runtime_preflight_is_bounded_document_free_and_nonpersistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    client_args = mock_transport(monkeypatch, handler)
    result = verify_openai_ocr_runtime(settings())

    assert result.model == "gpt-4.1-mini"
    assert requests == [
        {
            "input": "Reply with exactly the word READY.",
            "max_output_tokens": 16,
            "model": "gpt-4.1-mini",
            "store": False,
        }
    ]
    assert client_args["timeout"] == 15.0
    assert client_args["max_retries"] == 0


def test_runtime_preflight_rejects_a_missing_key_without_creating_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_client(**kwargs: Any) -> None:
        pytest.fail("A missing key must not create an OpenAI client")

    monkeypatch.setattr(openai_runtime, "OpenAI", fail_client)

    with pytest.raises(OpenAIRuntimeCheckError, match="not configured"):
        verify_openai_ocr_runtime(Settings(_env_file=None, OPENAI_API_KEY=""))


@pytest.mark.parametrize("status", [401, 429, 500])
def test_runtime_preflight_reports_safe_status_and_request_id_only(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"x-request-id": "req_preflight_safe"},
            json={"error": {"message": "PRIVATE_PROVIDER_DETAIL"}},
        )

    mock_transport(monkeypatch, handler)

    with pytest.raises(OpenAIRuntimeCheckError) as error:
        verify_openai_ocr_runtime(settings())

    detail = str(error.value)
    assert f"HTTP {status}" in detail
    assert "req_preflight_safe" in detail
    assert "PRIVATE_PROVIDER_DETAIL" not in detail


def test_runtime_preflight_rejects_an_incomplete_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json=response_body(status="failed")),
    )

    with pytest.raises(OpenAIRuntimeCheckError, match="did not complete"):
        verify_openai_ocr_runtime(settings())
