# Phase 5: grounded document questions and answers contract

Authorized scope: let a reviewer ask one question at a time about the active private driving licence. Answers must be grounded in the immutable Phase 2 reading and Phase 3 extraction, carry source-page references when answered, and clearly abstain when the document does not support an answer. This phase does not add accounts, long-term chat storage, OCR/extraction reprocessing, external web search, or answer highlighting/navigation.

## Source and provenance boundary

- The active document's Bearer capability remains mandatory. A question cannot read another document, and unknown, expired, deleted, and unauthorized documents remain indistinguishable as `DOCUMENT_NOT_FOUND` (404).
- Questions use the immutable source extraction and stored reading only. Phase 4 reviewer corrections and their edited flags are never treated as document evidence or sent to the answer provider.
- A supported direct field question is answered deterministically from its original evidence-backed extracted field. A missing direct source field produces an unavailable answer without provider work.
- Broader questions use a bounded lexical retrieval of reading blocks from the same document. The answer provider receives only that question and those selected blocks, never a file URL, document capability, review values, another document's text, or a browser conversation.
- Document blocks and the question are untrusted content. They cannot change the answer rules. The provider must return strict JSON, cite only supplied block IDs, and abstain instead of guessing, completing, interpreting portraits/signatures, decoding machine-readable marks, or relying on outside knowledge.
- The service validates every cited ID against the current selected document. A returned answer must have one or more citations; an unavailable answer has none. Provider details and document text remain out of public errors and logs.

## API and lifecycle

- `POST /api/documents/{document_id}/questions` accepts `{"question": "..."}` with the private Bearer capability. A question is trimmed, must be 1–500 characters, and unknown JSON keys are rejected.
- It requires a completed reading and source extraction. The existing `READING_REQUIRED` (409) and `EXTRACTION_NOT_FOUND` (404) responses apply before question work begins.
- `QuestionResult` contains `document_id`, the normalized `question`, `status` (`ANSWERED` or `UNAVAILABLE`), `answer`, `citations`, and `created_at`. An answered result has nonempty answer text and citations. An unavailable result has the fixed safe answer **“I couldn't find that in this document.”** and an empty citation list.
- Each citation comes from the stored reading and includes a block ID and one-based page number. The API response is `Cache-Control: no-store`.
- Questions and answers are not written to the repository. The browser keeps a small, current-session-only transcript and clears it on upload replacement or removal. Browser refresh loses the private capability and transcript.
- Calls are bounded by a configured question timeout, input/output limits, and process-local concurrent-question limit. Controlled provider/configuration/timeout/oversize/in-progress errors use dedicated question error codes and do not expose provider details.

## Frontend behavior

- The existing right-side chat preview becomes an accessible **Ask this document** form after the read → extract → fields lifecycle succeeds. It is unavailable before that point.
- Reviewers can type a question or select a clearly labelled suggested question. Submission disables conflicting chat actions while preserving the existing review form state.
- Each answer is rendered as text, never HTML. Answered responses show source-page chips; unavailable responses show no invented source. The interface explains that answers describe the uploaded source document, not saved reviewer corrections.
- A failed question keeps the typed question for retry. Upload replacement, removal, and component unmount cancel pending browser requests and clear chat-only state.

## Verification boundary

- Offline backend tests use a fake answer provider and cover deterministic direct lookup, retrieval selection, valid/invalid/missing/cross-document citations, abstention, prerequisites, capabilities, limits, controlled provider errors, and deletion/expiry races.
- Browser acceptance covers populated chat availability, successful cited answer, unavailable answer, failure/retry preservation, removal reset, keyboard submission, and compact layout. A live check may use the configured server-side key only after offline checks.
- Live evidence is reported separately for answer correctness, appropriate abstention, citation-page correctness, and both supplied fictional licence crops. This remains a two-example demonstration, not a general accuracy benchmark.
