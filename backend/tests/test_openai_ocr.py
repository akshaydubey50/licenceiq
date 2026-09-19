"""Offline contract checks use the real SDK with an in-memory HTTP transport."""

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import OpenAI

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.providers import openai_ocr
from app.providers.openai_ocr import OpenAIOCRProvider


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, OPENAI_API_KEY="test-key-not-a-credential", **overrides)


def response_body(
    text: str = '{"lines":["Example licence", "ABC 123", "नाम"]}',
    *,
    status: str = "completed",
    refusal: bool = False,
) -> dict[str, Any]:
    """Return a minimal actual Responses API envelope, not a fake SDK object."""
    part = (
        {"type": "refusal", "refusal": "Cannot transcribe"}
        if refusal
        else {"type": "output_text", "text": text, "annotations": []}
    )
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": [
            {
                "id": "msg_offline",
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

    monkeypatch.setattr(openai_ocr, "OpenAI", client)
    return captured


def test_vision_request_transcribes_without_storage_or_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    client_args = mock_transport(monkeypatch, handler)
    result = OpenAIOCRProvider(settings()).extract(
        b"prepared-image", "image/png", timeout_seconds=7
    )
    assert result.lines == ("Example licence", "ABC 123", "नाम")
    assert len(requests) == 1
    payload = requests[0]
    assert payload["store"] is False
    assert "tools" not in payload
    assert payload["max_output_tokens"] == 6000
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    image = payload["input"][0]["content"][1]
    assert image["detail"] == "high"
    assert image["image_url"] == (
        "data:image/png;base64," + base64.b64encode(b"prepared-image").decode()
    )
    assert "untrusted" in payload["instructions"]
    assert client_args["timeout"] == 7
    assert client_args["max_retries"] == 0


def test_empty_key_is_safe_and_does_not_create_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_client(**kwargs: Any) -> None:
        pytest.fail("Missing credentials must never create an SDK client")

    monkeypatch.setattr(openai_ocr, "OpenAI", fail_client)
    provider = OpenAIOCRProvider(Settings(_env_file=None, OPENAI_API_KEY=""))
    with pytest.raises(ApplicationError) as error:
        provider.extract(b"image", "image/png")
    assert error.value.code == "OCR_NOT_CONFIGURED"
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "body",
    [
        response_body("invalid private source text"),
        response_body('{"lines":[123]}'),
        response_body('{"lines":[],"name":"invented"}'),
        response_body(status="incomplete"),
        response_body(refusal=True),
        {**response_body(), "output": None},
        response_body(json.dumps({"lines": ["line"] * 2001})),
        response_body(json.dumps({"lines": ["a" * 64_001]})),
    ],
)
def test_invalid_or_truncated_output_is_not_evidence(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ApplicationError) as error:
        OpenAIOCRProvider(settings()).extract(b"image", "image/png")
    assert error.value.code == "OCR_PROVIDER_ERROR"
    assert "private source" not in str(error.value)


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_are_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "PRIVATE_PROVIDER_DETAIL"}})

    mock_transport(monkeypatch, handler)
    with pytest.raises(ApplicationError) as error:
        OpenAIOCRProvider(settings()).extract(b"image", "image/png")
    assert error.value.code == "OCR_PROVIDER_ERROR"
    assert "PRIVATE_PROVIDER_DETAIL" not in str(error.value)
    assert "PRIVATE_PROVIDER_DETAIL" not in caplog.text
    assert calls == 1


def test_timeout_is_safe_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("PRIVATE_REQUEST_DETAIL", request=request)

    client_args = mock_transport(monkeypatch, handler)
    with pytest.raises(ApplicationError) as error:
        OpenAIOCRProvider(settings()).extract(b"image", "image/jpeg", timeout_seconds=100)
    assert error.value.code == "OCR_TIMEOUT"
    assert "PRIVATE_REQUEST_DETAIL" not in str(error.value)
    assert client_args["timeout"] == 45


def test_blank_transcription_stays_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json=response_body('{"lines":[]}'))
    )
    assert OpenAIOCRProvider(settings()).extract(b"image", "image/png").lines == ()


def test_standard_env_key_is_secret_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")
    config = Settings(_env_file=None)
    assert config.openai_api_key.get_secret_value() == "test-secret-value"
    assert "test-secret-value" not in repr(config)
