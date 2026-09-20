"""Ephemeral document questions grounded in immutable source evidence."""

import hashlib
import math
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.models.document import (
    OUT_OF_SCOPE_ANSWER,
    Evidence,
    ExtractedField,
    ExtractionResult,
    QuestionCitation,
    QuestionRequest,
    QuestionResult,
    QuestionStatus,
    ReadingResult,
    SemanticIndex,
)
from app.providers.answer import (
    SAFE_UNAVAILABLE_ANSWER,
    AnswerCandidate,
    AnswerProvider,
    QuestionBlock,
    QuestionContext,
)
from app.providers.embeddings import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from app.providers.query_rewrite import (
    QueryRewriteProvider,
    QueryRewriteRequest,
    QueryRewriteResult,
)
from app.repositories.documents import (
    ChatPersistenceUnavailable,
    DocumentRepository,
    StoredDocumentRecord,
)
from app.schemas.common import ErrorCode
from app.services.documents import DocumentCredential, DocumentService
from app.services.question_guardrails import (
    QuestionGuardrail,
    QuestionGuardrailBlocked,
    QuestionGuardrailFailure,
)

_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "does",
    "document",
    "driving",
    "find",
    "from",
    "in",
    "is",
    "it",
    "licence",
    "license",
    "me",
    "of",
    "on",
    "please",
    "says",
    "show",
    "tell",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
}
_ANSWER_FRAMING_WORDS = {
    "authorised",
    "authorized",
    "document",
    "drive",
    "driving",
    "holder",
    "indicates",
    "licence",
    "license",
    "listed",
    "lists",
    "person",
    "says",
    "shows",
    "states",
}
_RELATIONSHIP_TERMS = {
    "daughter",
    "father",
    "guardian",
    "husband",
    "mother",
    "parent",
    "son",
    "spouse",
    "wife",
}
_DYNAMIC_FACT_ALIASES: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (("body height", "height", "how tall"), frozenset({"body height", "height", "stature"})),
    (("blood group", "blood type"), frozenset({"blood group", "blood type"})),
    (
        ("father name", "father s name", "name of father", "who is the father"),
        frozenset({"father", "father name", "father s name", "name of father"}),
    ),
    (
        ("mother name", "mother s name", "name of mother", "who is the mother"),
        frozenset({"mother", "mother name", "mother s name", "name of mother"}),
    ),
    (
        ("spouse name", "spouse s name", "husband name", "wife name"),
        frozenset(
            {
                "spouse",
                "spouse name",
                "spouse s name",
                "husband name",
                "wife name",
            }
        ),
    ),
    (
        ("guardian name", "guardian s name", "name of guardian"),
        frozenset({"guardian", "guardian name", "guardian s name", "name of guardian"}),
    ),
    (("restriction", "restrictions"), frozenset({"restriction", "restrictions"})),
    (("endorsement", "endorsements"), frozenset({"endorsement", "endorsements"})),
)
_GENERIC_OTHER_LABELS = {
    "date",
    "detail",
    "details",
    "information",
    "name",
    "number",
    "other",
    "value",
}
_MAX_DIRECT_LABEL_TERMS = 8
_LICENCE_SCOPE_TERMS = {
    "address",
    "authority",
    "authorised",
    "authorized",
    "birth",
    "class",
    "classes",
    "cov",
    "dl",
    "dob",
    "document",
    "drive",
    "driving",
    "endorsement",
    "expiry",
    "expiration",
    "expire",
    "expires",
    "holder",
    "issue",
    "issued",
    "issuing",
    "licence",
    "license",
    "live",
    "occupation",
    "person",
    "profession",
    "restriction",
    "restrictions",
    "rto",
    "valid",
    "validity",
    "vehicle",
    "vehicles",
    "vision",
    "work",
    "working",
}
_LICENCE_SCOPE_PHRASES = (
    "do for a living",
    "doing for a living",
    "job title",
    "place of residence",
    "resident location",
    "residence location",
    "residential location",
    "where does holder live",
    "where does the holder live",
)
_OBVIOUSLY_UNRELATED_TERMS = {
    "bake",
    "baking",
    "climate",
    "cook",
    "cooking",
    "cricket",
    "currency",
    "forecast",
    "football",
    "humidity",
    "ingredients",
    "javascript",
    "joke",
    "movie",
    "photosynthesis",
    "planet",
    "population",
    "president",
    "python",
    "rain",
    "recipe",
    "recipes",
    "snow",
    "song",
    "temperature",
    "weather",
}
_OBVIOUSLY_UNRELATED_PHRASES = (
    "capital of",
    "largest ocean",
    "prime minister",
    "speed of light",
    "tallest mountain",
    "who discovered",
    "who invented",
    "who wrote",
)
_ADDRESS_RETRIEVAL_TERMS = frozenset({"address", "residence", "residential"})
_RETRIEVAL_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"licence", "license", "dl", "number", "no"}),
    frozenset({"holder", "name", "person"}),
    frozenset({"birth", "dob", "born"}),
    frozenset({"issue", "issued", "authority", "rto"}),
    frozenset({"expiry", "expiration", "expire", "expires", "valid", "validity"}),
    _ADDRESS_RETRIEVAL_TERMS,
    frozenset({"vehicle", "vehicles", "class", "classes", "category", "cov"}),
    frozenset(
        {
            "endorsement",
            "endorsements",
            "restriction",
            "restrictions",
            "condition",
            "conditions",
        }
    ),
    frozenset({"vision", "eyesight", "corrective", "lens", "lenses"}),
)
_RRF_RANK_CONSTANT = 60


class QuestionService:
    """Answer from source extraction or bounded same-document reading blocks."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        document_service: DocumentService,
        answer_provider: AnswerProvider,
        embedding_provider: EmbeddingProvider,
        query_rewrite_provider: QueryRewriteProvider,
        question_guardrail: QuestionGuardrail,
        now_provider: Callable[[], datetime] | None = None,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.document_service = document_service
        self.answer_provider = answer_provider
        self.embedding_provider = embedding_provider
        self.query_rewrite_provider = query_rewrite_provider
        self.question_guardrail = question_guardrail
        self.now_provider = now_provider or (lambda: datetime.now(UTC))
        self.monotonic_provider = monotonic_provider or time.monotonic
        self._active_guard = threading.Lock()
        self._active_documents: set[str] = set()
        self._capacity = threading.BoundedSemaphore(settings.max_concurrent_questions)

    def ask(
        self,
        document_id: str,
        authorization: DocumentCredential,
        request: QuestionRequest,
    ) -> QuestionResult:
        """Answer one question and save only a validated eligible signed-user result."""
        initial = self.document_service.authorized_record(document_id, authorization)
        self._require_reading(initial)
        self._require_extraction(initial)

        self._begin_question(document_id)
        acquired = self._capacity.acquire(blocking=False)
        if not acquired:
            self._end_question(document_id)
            raise self._in_progress()
        try:
            snapshot = self.document_service.authorized_record(document_id, authorization)
            reading = self._require_reading(snapshot)
            extraction = self._require_extraction(snapshot)
            deadline = self.monotonic_provider() + self.settings.question_timeout_seconds
            self._guard_input(request.question, deadline)

            if self._is_out_of_scope(request.question):
                result = self._out_of_scope(snapshot.document_id, request.question)
                self._check_deadline(deadline)
                self._ensure_current(snapshot, authorization)
                self._persist_signed_result(snapshot, result)
                return result

            direct = self._direct_fields(request.question, extraction)
            if direct is not None:
                result = self._direct_result(
                    snapshot.document_id, request.question, reading, direct
                )
                result = self._guard_output(result, deadline)
                self._check_deadline(deadline)
                self._ensure_current(snapshot, authorization)
                self._persist_signed_result(snapshot, result)
                return result

            retrieval_query = self._retrieval_query(request, deadline)
            semantic_index = self._semantic_index(snapshot, reading, deadline)
            selected = self._retrieve(retrieval_query, reading, semantic_index, deadline)
            if not selected:
                result = self._unavailable(snapshot.document_id, request.question)
                self._check_deadline(deadline)
                self._ensure_current(snapshot, authorization)
                self._persist_signed_result(snapshot, result)
                return result

            try:
                context = QuestionContext(question=request.question, blocks=selected)
            except (ValidationError, ValueError, TypeError):
                raise self._too_large() from None

            try:
                candidate = self.answer_provider.answer_question(
                    context,
                    timeout_seconds=self._remaining(deadline),
                )
            except ApplicationError as exc:
                raise self._controlled_provider_error(exc) from None
            except Exception:
                # Provider errors can contain private document or model output.
                raise self._provider_error() from None
            self._check_deadline(deadline)
            result = self._provider_result(
                snapshot.document_id, request.question, selected, candidate
            )
            result = self._guard_output(result, deadline)
            self._ensure_current(snapshot, authorization)
            self._persist_signed_result(snapshot, result)
            return result
        finally:
            self._capacity.release()
            self._end_question(document_id)

    def _persist_signed_result(
        self, snapshot: StoredDocumentRecord, result: QuestionResult
    ) -> None:
        """Best-effort save after all grounding, citation, guardrail, and freshness checks."""
        if (
            snapshot.owner_subject is None
            or self.settings.document_metadata_backend != "postgres"
            or not hasattr(self.repository, "save_chat_turn_if_current")
        ):
            return
        try:
            self.repository.save_chat_turn_if_current(snapshot, result, self.now_provider())
        except ChatPersistenceUnavailable:
            # The question remains usable while the dedicated history endpoints expose
            # persistence unavailability to the frontend.
            return

    @staticmethod
    def _require_reading(record: StoredDocumentRecord) -> ReadingResult:
        if record.reading is None:
            raise ApplicationError(
                ErrorCode.READING_REQUIRED,
                "Read the document before asking questions.",
                409,
            )
        return record.reading

    @staticmethod
    def _require_extraction(record: StoredDocumentRecord) -> ExtractionResult:
        if record.extraction is None:
            raise ApplicationError(
                ErrorCode.EXTRACTION_NOT_FOUND,
                "The document has not been extracted yet.",
                404,
            )
        return record.extraction

    @staticmethod
    def _direct_fields(
        question: str,
        extraction: ExtractionResult,
    ) -> tuple[ExtractedField, ...] | None:
        normalized = QuestionService._normalize_phrase(question)
        licence = extraction.licence
        matches: list[tuple[ExtractedField, ...]] = []
        asks_relationship_name = QuestionService._contains_phrase(normalized, "name") and any(
            QuestionService._contains_phrase(normalized, term) for term in _RELATIONSHIP_TERMS
        )
        patterns: tuple[tuple[tuple[str, ...], tuple[ExtractedField, ...]], ...] = (
            (("full name", "holder name", "licence holder"), (licence.full_name,)),
            (
                ("licence number", "license number", "dl number", "dl no"),
                (licence.licence_number,),
            ),
            (("date of birth", "birth date", "dob"), (licence.date_of_birth,)),
            (("date of issue", "issue date", "issued on"), (licence.date_of_issue,)),
            (
                (
                    "date of expiry",
                    "expiry date",
                    "expiration date",
                    "valid until",
                    "valid till",
                    "expires",
                    "expire",
                ),
                (licence.date_of_expiry,),
            ),
            (
                (
                    "address",
                    "resident location",
                    "residence location",
                    "residential location",
                    "where does holder live",
                    "where does the holder live",
                ),
                (licence.address,),
            ),
            (
                (
                    "vehicle class",
                    "vehicle classes",
                    "class of vehicle",
                    "cov",
                    "can drive",
                    "vehicles",
                ),
                licence.vehicle_classes,
            ),
            (("issuing authority", "issued by", "rto"), (licence.issuing_authority,)),
        )
        for phrases, fields in patterns:
            if any(QuestionService._contains_phrase(normalized, phrase) for phrase in phrases):
                matches.append(fields)
        has_explicit_holder_name = any(
            QuestionService._contains_phrase(normalized, phrase)
            for phrase in ("full name", "holder name", "licence holder")
        )
        if (
            QuestionService._contains_phrase(normalized, "name")
            and not asks_relationship_name
            and not has_explicit_holder_name
        ):
            matches.append((licence.full_name,))

        other_by_label: dict[str, list[ExtractedField]] = {}
        for name, field in licence.other_information.items():
            label = QuestionService._normalize_phrase(name)
            if label:
                other_by_label.setdefault(label, []).append(field)
        other_matches: set[str] = set()
        for question_aliases, label_aliases in _DYNAMIC_FACT_ALIASES:
            if any(
                QuestionService._contains_phrase(normalized, alias) for alias in question_aliases
            ):
                other_matches.update(label for label in other_by_label if label in label_aliases)

        for label in other_by_label:
            terms = label.split()
            if (
                label not in _GENERIC_OTHER_LABELS
                and len(terms) <= _MAX_DIRECT_LABEL_TERMS
                and QuestionService._contains_phrase(normalized, label)
            ):
                other_matches.add(label)

        matches.extend(
            (field,) for label in sorted(other_matches) for field in other_by_label[label]
        )

        if asks_relationship_name and not matches:
            # Never reinterpret a missing relationship name as the holder's name.
            return ()
        return matches[0] if len(matches) == 1 else None

    def _direct_result(
        self,
        document_id: str,
        question: str,
        reading: ReadingResult,
        fields: tuple[ExtractedField, ...],
    ) -> QuestionResult:
        present = tuple(field for field in fields if field.value is not None)
        if not present:
            return self._unavailable(document_id, question)

        reading_index = self._evidence_index(reading)
        citations: list[QuestionCitation] = []
        seen: set[str] = set()
        for field in present:
            if not field.evidence:
                return self._unavailable(document_id, question)
            for evidence in field.evidence:
                block_id = evidence.block_id
                if (
                    block_id is None
                    or block_id not in reading_index
                    or reading_index[block_id] != evidence
                ):
                    return self._unavailable(document_id, question)
                if block_id not in seen:
                    seen.add(block_id)
                    citations.append(
                        QuestionCitation(block_id=block_id, page_number=evidence.page_number)
                    )
        answer = ", ".join(field.value for field in present if field.value is not None)
        if len(answer) > 4096 or len(citations) > 20:
            raise self._too_large()
        return QuestionResult(
            document_id=document_id,
            question=question,
            status=QuestionStatus.ANSWERED,
            answer=answer,
            citations=tuple(citations),
            created_at=self.now_provider(),
        )

    def _semantic_index(
        self,
        snapshot: StoredDocumentRecord,
        reading: ReadingResult,
        deadline: float,
    ) -> SemanticIndex | None:
        evidence = self._bounded_index_evidence(reading)
        if not evidence:
            return None
        block_ids = tuple(self._required_block_id(item) for item in evidence)
        reading_sha256 = self._reading_sha256(reading)
        cached = snapshot.semantic_index
        if (
            cached is not None
            and cached.document_id == snapshot.document_id
            and cached.reading_sha256 == reading_sha256
            and cached.model == self.settings.question_embedding_model
            and cached.dimensions == self.settings.question_embedding_dimensions
            and cached.block_ids == block_ids
        ):
            return cached

        result = self._embed(
            EmbeddingRequest(texts=tuple(item.source_text for item in evidence)),
            deadline,
        )
        vectors = self._validated_vectors(result, len(evidence))
        try:
            semantic_index = SemanticIndex(
                document_id=snapshot.document_id,
                reading_sha256=reading_sha256,
                model=self.settings.question_embedding_model,
                dimensions=self.settings.question_embedding_dimensions,
                block_ids=block_ids,
                vectors=vectors,
            )
        except (ValidationError, ValueError, TypeError):
            raise self._provider_error() from None
        try:
            published = self.repository.save_semantic_index_if_current(
                snapshot,
                semantic_index,
                self.now_provider(),
            )
        except OSError:
            raise self._provider_error() from None
        if not published:
            self.document_service.cleanup_expired()
            raise self.document_service.not_found()
        return semantic_index

    def _retrieve(
        self,
        retrieval_query: str,
        reading: ReadingResult,
        semantic_index: SemanticIndex | None,
        deadline: float,
    ) -> tuple[QuestionBlock, ...]:
        query_terms = self._expanded_retrieval_terms(retrieval_query)
        if semantic_index is None:
            return ()
        result = self._embed(EmbeddingRequest(texts=(retrieval_query,)), deadline)
        query_vector = self._validated_vectors(result, 1)[0]
        vectors_by_id = dict(zip(semantic_index.block_ids, semantic_index.vectors, strict=True))

        candidates: list[tuple[int, Evidence, int, float]] = []
        for page in reading.pages:
            for evidence in page.blocks:
                block_terms = self._terms(evidence.source_text)
                matches = sum(1 for term in query_terms if term in block_terms)
                block_id = evidence.block_id
                vector = vectors_by_id.get(block_id) if block_id is not None else None
                if vector is not None:
                    semantic_score = self._cosine(query_vector, vector)
                else:
                    semantic_score = -1.0
                candidates.append((len(candidates), evidence, matches, semantic_score))

        lexical_rank = {
            order: rank
            for rank, (order, _evidence, _matches, _semantic) in enumerate(
                sorted(
                    (item for item in candidates if item[2] > 0),
                    key=lambda item: (-item[2], item[0]),
                ),
                start=1,
            )
        }
        semantic_rank = {
            order: rank
            for rank, (order, _evidence, _matches, _semantic) in enumerate(
                sorted(candidates, key=lambda item: (-item[3], item[0])),
                start=1,
            )
        }
        ranked: list[tuple[float, int, int, int, Evidence]] = []
        for order, evidence, matches, _semantic_score in candidates:
            reciprocal_score = 1.0 / (_RRF_RANK_CONSTANT + semantic_rank[order])
            lexical_position = lexical_rank.get(order)
            if lexical_position is not None:
                reciprocal_score += 1.0 / (_RRF_RANK_CONSTANT + lexical_position)
            ranked.append((-reciprocal_score, -matches, semantic_rank[order], order, evidence))
        ranked.sort(key=lambda item: item[:4])

        selected: list[QuestionBlock] = []
        selected_characters = 0
        for _, _, _, _, evidence in ranked:
            if len(selected) >= self.settings.question_max_selected_blocks:
                break
            block_id = evidence.block_id
            if block_id is None:
                raise self._provider_error()
            next_size = selected_characters + len(evidence.source_text)
            if not selected and next_size > self.settings.question_max_selected_characters:
                raise self._too_large()
            if next_size > self.settings.question_max_selected_characters:
                continue
            try:
                selected.append(
                    QuestionBlock(
                        block_id=block_id,
                        page_number=evidence.page_number,
                        text=evidence.source_text,
                    )
                )
            except (ValidationError, ValueError, TypeError):
                raise self._too_large() from None
            selected_characters = next_size
        return tuple(selected)

    def _retrieval_query(self, request: QuestionRequest, deadline: float) -> str:
        """Rewrite only conversational questions and safely retain the original on failure."""
        if not request.history:
            return request.question
        try:
            rewrite_request = QueryRewriteRequest(
                question=request.question,
                previous_questions=tuple(item.question for item in request.history[-3:]),
            )
            result = self.query_rewrite_provider.rewrite(
                rewrite_request,
                timeout_seconds=min(
                    self.settings.question_rewrite_timeout_seconds,
                    self._remaining(deadline),
                ),
            )
            if not isinstance(result, QueryRewriteResult):
                result = QueryRewriteResult.model_validate(result)
            return result.query
        except Exception:
            # Rewriting is retrieval assistance only. Never turn its failure into a Q&A failure.
            return request.question

    @staticmethod
    def _expanded_retrieval_terms(value: str) -> set[str]:
        """Expand a small licence-domain vocabulary before deterministic lexical ranking."""
        terms = QuestionService._terms(value) - _STOP_WORDS
        expanded = set(terms)
        for group in _RETRIEVAL_SYNONYM_GROUPS:
            if terms & group:
                expanded.update(group)
        if "location" in terms and terms & {"resident", "residence", "residential"}:
            expanded.update(_ADDRESS_RETRIEVAL_TERMS)
        return expanded

    def _bounded_index_evidence(self, reading: ReadingResult) -> tuple[Evidence, ...]:
        selected: list[Evidence] = []
        characters = 0
        for page in reading.pages:
            for evidence in page.blocks:
                if len(selected) >= self.settings.question_embedding_max_blocks:
                    return tuple(selected)
                self._required_block_id(evidence)
                next_size = characters + len(evidence.source_text)
                if not selected and next_size > self.settings.question_embedding_max_characters:
                    raise self._too_large()
                if next_size > self.settings.question_embedding_max_characters:
                    return tuple(selected)
                selected.append(evidence)
                characters = next_size
        return tuple(selected)

    def _embed(self, request: EmbeddingRequest, deadline: float) -> EmbeddingResult:
        try:
            result = self.embedding_provider.embed(
                request,
                timeout_seconds=min(
                    self.settings.question_embedding_timeout_seconds,
                    self._remaining(deadline),
                ),
            )
        except ApplicationError as exc:
            raise self._controlled_provider_error(exc) from None
        except Exception:
            raise self._provider_error() from None
        self._check_deadline(deadline)
        if not isinstance(result, EmbeddingResult):
            try:
                result = EmbeddingResult.model_validate(result)
            except (ValidationError, ValueError, TypeError):
                raise self._provider_error() from None
        return result

    def _validated_vectors(
        self,
        result: EmbeddingResult,
        expected_count: int,
    ) -> tuple[tuple[float, ...], ...]:
        if (
            result.model != self.settings.question_embedding_model
            or result.dimensions != self.settings.question_embedding_dimensions
            or len(result.vectors) != expected_count
        ):
            raise self._provider_error()
        for vector in result.vectors:
            if (
                len(vector) != self.settings.question_embedding_dimensions
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
            ):
                raise self._provider_error()
        return result.vectors

    @staticmethod
    def _required_block_id(evidence: Evidence) -> str:
        if evidence.block_id is None:
            raise QuestionService._provider_error()
        return evidence.block_id

    @staticmethod
    def _reading_sha256(reading: ReadingResult) -> str:
        payload = reading.model_dump_json().encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        dot_product = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            raise QuestionService._provider_error()
        score = dot_product / (left_norm * right_norm)
        if not math.isfinite(score):
            raise QuestionService._provider_error()
        return score

    def _provider_result(
        self,
        document_id: str,
        question: str,
        selected: tuple[QuestionBlock, ...],
        candidate: AnswerCandidate,
    ) -> QuestionResult:
        if not isinstance(candidate, AnswerCandidate):
            try:
                candidate = AnswerCandidate.model_validate(candidate)
            except (ValidationError, ValueError, TypeError):
                raise self._provider_error() from None
        if candidate.status == "UNAVAILABLE":
            if candidate.answer != SAFE_UNAVAILABLE_ANSWER or candidate.block_ids:
                raise self._provider_error()
            return self._unavailable(document_id, question)
        if (
            candidate.status != "ANSWERED"
            or not candidate.answer
            or candidate.answer != candidate.answer.strip()
            or len(candidate.answer) > 4096
            or not candidate.block_ids
            or len(candidate.block_ids) != len(set(candidate.block_ids))
        ):
            raise self._provider_error()

        selected_by_id = {block.block_id: block for block in selected}
        if any(block_id not in selected_by_id for block_id in candidate.block_ids):
            raise self._provider_error()
        if not self._answer_is_supported(candidate.answer, candidate.block_ids, selected_by_id):
            return self._unavailable(document_id, question)
        citations = tuple(
            QuestionCitation(
                block_id=block_id,
                page_number=selected_by_id[block_id].page_number,
            )
            for block_id in candidate.block_ids
        )
        return QuestionResult(
            document_id=document_id,
            question=question,
            status=QuestionStatus.ANSWERED,
            answer=candidate.answer,
            citations=citations,
            created_at=self.now_provider(),
        )

    @staticmethod
    def _answer_is_supported(
        answer: str,
        block_ids: tuple[str, ...],
        selected_by_id: dict[str, QuestionBlock],
    ) -> bool:
        """Require every meaningful answer term to occur in its cited source blocks."""
        cited_text = " ".join(selected_by_id[block_id].text for block_id in block_ids)
        normalized_answer = QuestionService._normalize_phrase(answer)
        normalized_source = QuestionService._normalize_phrase(cited_text)
        if normalized_answer and normalized_answer in normalized_source:
            return True
        answer_terms = QuestionService._terms(answer) - _STOP_WORDS - _ANSWER_FRAMING_WORDS
        source_terms = QuestionService._terms(cited_text)
        return bool(answer_terms) and answer_terms.issubset(source_terms)

    def _guard_input(self, question: str, deadline: float) -> None:
        try:
            self.question_guardrail.check_input(
                question,
                timeout_seconds=self._remaining(deadline),
            )
        except QuestionGuardrailBlocked:
            raise self._blocked() from None
        except QuestionGuardrailFailure:
            raise self._guard_error() from None
        self._check_deadline(deadline)

    def _guard_output(self, result: QuestionResult, deadline: float) -> QuestionResult:
        if result.status is QuestionStatus.UNAVAILABLE:
            return result
        try:
            self.question_guardrail.check_output(
                result.answer,
                timeout_seconds=self._remaining(deadline),
            )
        except QuestionGuardrailBlocked:
            return self._unavailable(result.document_id, result.question)
        except QuestionGuardrailFailure:
            raise self._guard_error() from None
        self._check_deadline(deadline)
        return result

    def _ensure_current(
        self,
        snapshot: StoredDocumentRecord,
        authorization: DocumentCredential,
    ) -> None:
        current = self.document_service.authorized_record(snapshot.document_id, authorization)
        if (
            current.storage_key != snapshot.storage_key
            or current.created_at != snapshot.created_at
            or current.access_token_hash != snapshot.access_token_hash
            or current.reading != snapshot.reading
            or current.extraction != snapshot.extraction
        ):
            raise self.document_service.not_found()

    @staticmethod
    def _evidence_index(reading: ReadingResult) -> dict[str, Evidence]:
        indexed: dict[str, Evidence] = {}
        for page in reading.pages:
            for evidence in page.blocks:
                block_id = evidence.block_id
                if block_id is None or block_id in indexed:
                    raise QuestionService._provider_error()
                indexed[block_id] = evidence
        return indexed

    def _unavailable(self, document_id: str, question: str) -> QuestionResult:
        return QuestionResult(
            document_id=document_id,
            question=question,
            status=QuestionStatus.UNAVAILABLE,
            answer=SAFE_UNAVAILABLE_ANSWER,
            citations=(),
            created_at=self.now_provider(),
        )

    def _out_of_scope(self, document_id: str, question: str) -> QuestionResult:
        return QuestionResult(
            document_id=document_id,
            question=question,
            status=QuestionStatus.OUT_OF_SCOPE,
            answer=OUT_OF_SCOPE_ANSWER,
            citations=(),
            created_at=self.now_provider(),
        )

    @staticmethod
    def _is_out_of_scope(question: str) -> bool:
        """Recognize only explicit unrelated topics; ambiguous prompts stay grounded."""
        normalized = QuestionService._normalize_phrase(question)
        terms = set(normalized.split())
        if terms & _LICENCE_SCOPE_TERMS or any(
            QuestionService._contains_phrase(normalized, phrase)
            for phrase in _LICENCE_SCOPE_PHRASES
        ):
            return False
        if terms & _OBVIOUSLY_UNRELATED_TERMS:
            return True
        return any(
            QuestionService._contains_phrase(normalized, phrase)
            for phrase in _OBVIOUSLY_UNRELATED_PHRASES
        )

    @staticmethod
    def _normalize_phrase(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(_WORD_PATTERN.findall(normalized))

    @staticmethod
    def _contains_phrase(normalized: str, phrase: str) -> bool:
        return f" {phrase} " in f" {normalized} "

    @staticmethod
    def _terms(value: str) -> set[str]:
        return set(_WORD_PATTERN.findall(unicodedata.normalize("NFKC", value).casefold()))

    def _begin_question(self, document_id: str) -> None:
        with self._active_guard:
            if document_id in self._active_documents:
                raise self._in_progress()
            self._active_documents.add(document_id)

    def _end_question(self, document_id: str) -> None:
        with self._active_guard:
            self._active_documents.discard(document_id)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.monotonic_provider()
        if remaining <= 0:
            raise self._timeout()
        return remaining

    def _check_deadline(self, deadline: float) -> None:
        _ = self._remaining(deadline)

    @staticmethod
    def _controlled_provider_error(exc: ApplicationError) -> ApplicationError:
        """Preserve only known categories while replacing provider-owned messages."""
        if exc.code is ErrorCode.QUESTION_NOT_CONFIGURED:
            return ApplicationError(
                ErrorCode.QUESTION_NOT_CONFIGURED,
                "Document questions are not configured on the server.",
                503,
            )
        if exc.code is ErrorCode.QUESTION_TIMEOUT:
            return QuestionService._timeout()
        if exc.code is ErrorCode.QUESTION_TOO_LARGE:
            return QuestionService._too_large()
        return QuestionService._provider_error()

    @staticmethod
    def invalid_question() -> ApplicationError:
        return ApplicationError(
            ErrorCode.INVALID_QUESTION,
            "The document question is invalid.",
            400,
        )

    @staticmethod
    def _in_progress() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_IN_PROGRESS,
            "This document already has a question in progress. Please try again shortly.",
            409,
        )

    @staticmethod
    def _provider_error() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_PROVIDER_ERROR,
            "The document question service could not answer this question. Please try again.",
            502,
        )

    @staticmethod
    def _blocked() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_BLOCKED,
            "This question cannot be processed by the document assistant.",
            400,
        )

    @staticmethod
    def _guard_error() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_GUARD_ERROR,
            "Document question safeguards are temporarily unavailable.",
            503,
        )

    @staticmethod
    def _timeout() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_TIMEOUT,
            "The document question took too long. Please try again.",
            504,
        )

    @staticmethod
    def _too_large() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_TOO_LARGE,
            "The selected document evidence is too large to answer safely.",
            422,
        )
