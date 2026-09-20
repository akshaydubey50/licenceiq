"""Local NeMo input/output rails for document questions.

The rails deliberately receive only the user's question or the final answer. They never
receive OCR text, retrieved blocks, licence fields, credentials, or provider configuration.
"""

import asyncio
import re
import unicodedata
import warnings
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, cast

from nemoguardrails import LLMRails, RailsConfig  # type: ignore[import-untyped]
from nemoguardrails.actions import action  # type: ignore[import-untyped]
from nemoguardrails.rails.llm.options import (  # type: ignore[import-untyped]
    RailsResult,
    RailStatus,
    RailType,
)

from app.core.config import Settings

_COLANG = """
define bot refuse to respond
  "This request cannot be processed."

define subflow licenceiq input guard
  $is_allowed = execute LicenceIQInputGuardAction(text=$user_message)
  if not $is_allowed
    bot refuse to respond
    stop

define subflow licenceiq output guard
  $is_allowed = execute LicenceIQOutputGuardAction(text=$bot_message)
  if not $is_allowed
    bot refuse to respond
    stop
"""

_CONFIG = """
models: []
rails:
  input:
    flows:
      - licenceiq input guard
  output:
    flows:
      - licenceiq output guard
"""

_INPUT_POLICY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\b(?:ignore|disregard|override|forget|bypass)\b.{0,80}"
        r"\b(?:previous|prior|above|all|system|developer)\b.{0,50}"
        r"\b(?:instruction|prompt|rule|policy)s?\b",
        r"\b(?:reveal|show|print|display|repeat|expose|leak|provide)\b.{0,80}"
        r"\b(?:system|developer|hidden|internal)\b.{0,50}"
        r"\b(?:prompt|message|instruction|policy|rule)s?\b",
        r"\b(?:system prompt|developer message|hidden prompt|internal instructions?)\b",
        r"\b(?:jailbreak|do anything now|developer mode|prompt injection)\b",
        r"(?:^|\n)\s*(?:system|developer|assistant)\s*:",
    )
)

_OUTPUT_POLICY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\b(?:system prompt|developer message|hidden prompt|internal instructions?)\b",
        r"\b(?:ignore|disregard|override|bypass)\b.{0,80}"
        r"\b(?:instruction|prompt|rule|policy)s?\b",
        r"(?:^|\n)\s*(?:system|developer)\s*:",
    )
)


class QuestionGuardrailBlocked(Exception):
    """A deterministic rail rejected the supplied question or answer."""


class QuestionGuardrailFailure(Exception):
    """The enabled rail could not initialize or finish safely."""


class QuestionGuardrail(Protocol):
    """Small boundary used by the synchronous question service."""

    def check_input(self, question: str, *, timeout_seconds: float) -> None: ...

    def check_output(self, answer: str, *, timeout_seconds: float) -> None: ...


class _RailsEngine(Protocol):
    async def check_async(
        self,
        messages: list[dict[str, str]],
        rail_types: list[RailType] | None = None,
    ) -> RailsResult: ...


class DisabledQuestionGuardrail:
    """Permit an explicit local opt-out when diagnosing or comparing behaviour."""

    def check_input(self, question: str, *, timeout_seconds: float) -> None:
        del question, timeout_seconds

    def check_output(self, answer: str, *, timeout_seconds: float) -> None:
        del answer, timeout_seconds


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _passes_input_policy(text: str) -> bool:
    normalized = _normalized(text)
    return not any(pattern.search(normalized) for pattern in _INPUT_POLICY_PATTERNS)


def _passes_output_policy(text: str) -> bool:
    normalized = _normalized(text)
    return not any(pattern.search(normalized) for pattern in _OUTPUT_POLICY_PATTERNS)


@action(name="LicenceIQInputGuardAction", execute_async=True)  # type: ignore[untyped-decorator]
async def _input_guard_action(text: str) -> bool:
    """Block prompt-control attempts without calling an LLM or external service."""
    return _passes_input_policy(text)


@action(name="LicenceIQOutputGuardAction", execute_async=True)  # type: ignore[untyped-decorator]
async def _output_guard_action(text: str) -> bool:
    """Block policy leakage while permitting authorized licence data."""
    return _passes_output_policy(text)


RailsFactory = Callable[[], _RailsEngine]


class NeMoQuestionGuardrail:
    """Run bounded local custom rails through NeMo Guardrails' async API."""

    def __init__(self, settings: Settings, rails_factory: RailsFactory | None = None) -> None:
        self.timeout_seconds = settings.question_guardrail_timeout_seconds
        self._rails: _RailsEngine | None = None
        self._initialization_failed = False
        try:
            self._rails = (rails_factory or self._build_rails)()
        except Exception:
            # Library/configuration details can contain installation paths and are never public.
            self._initialization_failed = True

    @staticmethod
    def _build_rails() -> _RailsEngine:
        # NeMo 0.24 warns that the legacy flow list will change. Its current Colang 2
        # check_async path cannot run custom check rails without an LLM, while this supported
        # local Colang flow path is deterministic and makes no provider calls.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Configuring input/output rails in config.yml is deprecated.*",
                category=FutureWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message="Use 'nim_base_url' instead.*",
                category=DeprecationWarning,
                module="nemoguardrails\\.library\\.jailbreak_detection\\.rail_config",
            )
            config = RailsConfig.from_content(colang_content=_COLANG, yaml_content=_CONFIG)
            rails = LLMRails(config)
        rails.register_action(_input_guard_action)
        rails.register_action(_output_guard_action)
        return cast(_RailsEngine, rails)

    def check_input(self, question: str, *, timeout_seconds: float) -> None:
        self._check(
            question, role="user", rail_type=RailType.INPUT, timeout_seconds=timeout_seconds
        )

    def check_output(self, answer: str, *, timeout_seconds: float) -> None:
        self._check(
            answer,
            role="assistant",
            rail_type=RailType.OUTPUT,
            timeout_seconds=timeout_seconds,
        )

    def _check(
        self,
        text: str,
        *,
        role: str,
        rail_type: RailType,
        timeout_seconds: float,
    ) -> None:
        if self._initialization_failed or self._rails is None:
            raise QuestionGuardrailFailure from None
        rails = self._rails
        bounded_timeout = min(self.timeout_seconds, timeout_seconds)
        if bounded_timeout <= 0:
            raise QuestionGuardrailFailure from None

        async def execute() -> RailsResult:
            operation: Coroutine[Any, Any, RailsResult] = rails.check_async(
                [{"role": role, "content": text}],
                rail_types=[rail_type],
            )
            return await asyncio.wait_for(operation, timeout=bounded_timeout)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                result = asyncio.run(execute())
            except Exception:
                raise QuestionGuardrailFailure from None
        else:
            # QuestionService is deliberately executed in a worker thread. Fail closed if a
            # caller bypasses that boundary instead of nesting a sync NeMo call in an event loop.
            raise QuestionGuardrailFailure from None

        if result.status is not RailStatus.PASSED or result.content != text:
            raise QuestionGuardrailBlocked from None


def build_question_guardrail(settings: Settings) -> QuestionGuardrail:
    """Build active NeMo rails unless an explicit local opt-out is configured."""
    if not settings.question_guardrails_enabled:
        return DisabledQuestionGuardrail()
    return NeMoQuestionGuardrail(settings)
