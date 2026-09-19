"""Offline OpenAI embedding checks use the real SDK with mock HTTP transport."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.providers import openai_embeddings
from app.providers.embeddings import EmbeddingRequest
from app.providers.openai_embeddings import OpenAIEmbeddingProvider


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, OPENAI_API_KEY="test-key-not-a-credential", **overrides)


def response_body(
    vectors: list[list[float]],
    *,
    indexes: list[int] | None = None,
) -> dict[str, Any]:
    ordered_indexes = indexes if indexes is not None else list(range(len(vectors)))
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vector, "index": index}
            for vector, index in zip(vectors, ordered_indexes, strict=True)
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }


def mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> OpenAI:
        captured.update(kwargs)
        return OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)

    monkeypatch.setattr(openai_embeddings, "OpenAI", client)
    return captured


def test_request_uses_configured_model_dimensions_float_format_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    first = [1.0] + [0.0] * 255
    second = [0.0, 1.0] + [0.0] * 254

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        # Deliberately reverse transport order; indexes define request order.
        return httpx.Response(200, json=response_body([second, first], indexes=[1, 0]))

    client_args = mock_transport(monkeypatch, handler)
    result = OpenAIEmbeddingProvider(settings()).embed(
        EmbeddingRequest(texts=("first block", "second block")),
        timeout_seconds=7,
    )
    assert result.vectors == (tuple(first), tuple(second))
    assert requests == [
        {
            "input": ["first block", "second block"],
            "model": "text-embedding-3-small",
            "dimensions": 256,
            "encoding_format": "float",
        }
    ]
    assert client_args["timeout"] == 7
    assert client_args["max_retries"] == 0


def test_embedding_settings_defaults_and_bounds() -> None:
    config = settings()
    assert config.question_embedding_model == "text-embedding-3-small"
    assert config.question_embedding_dimensions == 256
    assert config.question_embedding_timeout_seconds == 15
    assert config.question_embedding_max_blocks == 256
    assert config.question_embedding_max_characters == 100_000
    with pytest.raises(ValidationError):
        settings(question_embedding_dimensions=0)
    with pytest.raises(ValidationError):
        settings(question_embedding_timeout_seconds=121)


def test_missing_key_does_not_create_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_client(**kwargs: Any) -> None:
        pytest.fail("Missing credentials must never create an SDK client")

    monkeypatch.setattr(openai_embeddings, "OpenAI", fail_client)
    with pytest.raises(ApplicationError) as error:
        OpenAIEmbeddingProvider(Settings(_env_file=None, OPENAI_API_KEY="")).embed(
            EmbeddingRequest(texts=("question",))
        )
    assert error.value.code == "QUESTION_NOT_CONFIGURED"
    assert error.value.status_code == 503


def test_input_bounds_fail_before_client_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_client(**kwargs: Any) -> None:
        pytest.fail("Oversize embedding input must not create an SDK client")

    monkeypatch.setattr(openai_embeddings, "OpenAI", fail_client)
    provider = OpenAIEmbeddingProvider(settings(question_embedding_max_characters=5))
    with pytest.raises(ApplicationError) as error:
        provider.embed(EmbeddingRequest(texts=("too long",)))
    assert error.value.code == "QUESTION_TOO_LARGE"


@pytest.mark.parametrize(
    "body",
    [
        response_body([[1.0] + [0.0] * 254]),
        response_body(
            [[1.0] + [0.0] * 255, [0.0, 1.0] + [0.0] * 254],
            indexes=[0, 0],
        ),
        response_body([[float("nan")] + [0.0] * 255]),
        response_body([[0.0] * 256]),
    ],
)
def test_malformed_nonfinite_or_unusable_vectors_are_controlled(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
) -> None:
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ApplicationError) as error:
        OpenAIEmbeddingProvider(settings()).embed(EmbeddingRequest(texts=("question",)))
    assert error.value.code == "QUESTION_PROVIDER_ERROR"


def test_timeout_is_bounded_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("PRIVATE_EMBEDDING_DETAIL", request=request)

    client_args = mock_transport(monkeypatch, handler)
    with pytest.raises(ApplicationError) as error:
        OpenAIEmbeddingProvider(settings()).embed(
            EmbeddingRequest(texts=("question",)),
            timeout_seconds=100,
        )
    assert error.value.code == "QUESTION_TIMEOUT"
    assert "PRIVATE_EMBEDDING_DETAIL" not in str(error.value)
    assert client_args["timeout"] == 15
    assert client_args["max_retries"] == 0
    assert calls == 1
