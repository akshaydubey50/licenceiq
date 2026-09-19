# Phase 5: grounded document questions and answers

Status: complete on 19 September 2026. This phase turns the processed private licence into a source-grounded question interface. It answers direct document-field questions, retrieves bounded reading blocks for broader questions, shows source pages for supported answers, and returns a fixed unavailable response when the document does not support a claim. The detailed boundary is [the Phase 5 contract](PHASE_5_CONTRACT.md).

## What changed

The backend adds `POST /api/documents/{document_id}/questions`. It requires the existing private Bearer capability, a completed reading, and an extraction. Direct questions such as licence number, expiry, holder name, vehicle classes, and extracted additional-information labels are resolved from immutable source extraction evidence without a provider call. Missing direct source values produce **“I couldn't find that in this document.”**.

For a broader question, the service ranks matching reading blocks from the same document within strict block and character limits. The OpenAI adapter receives only the question and those selected blocks, with strict JSON output, no tools, no SDK retries, `store=False`, and a configured timeout. An answered response must cite one or more selected block IDs. The service resolves every citation against the current document's reading and rejects malformed, duplicate, unknown, cross-document, uncited, oversized, or late results. Reviewer changes are never read by the answer service or sent to the provider.

The browser replaces the former chat placeholder with an accessible **Ask this document** form after read → extract → fields completes. It supports typed and suggested questions, Enter submission, a five-entry in-memory transcript, retry-preserved input, page chips for cited answers, and an explicit source-versus-review explanation. It renders answer text only, validates that every returned citation matches its locally held reading, and clears/cancels chat state on replacement, removal, and unmount.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) selected the strong tier for both independently implemented units. The coordinator fixed the shared contract before dispatch, reviewed returned code, applied one bounded browser citation-validation correction, and performed integration and live acceptance.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Grounded answer transport, retrieval, service lifecycle, API, provider, and tests | [8/8, high risk](routing/phase-5-backend-assessment.json) | `/root/phase5_backend`, `gpt-5.6-sol` / `high` | 1 / 0 | Accepted |
| Document chat UI, response validation, lifecycle state, and responsive styles | [6/8, medium risk](routing/phase-5-frontend-assessment.json) | `/root/phase5_frontend`, `gpt-5.6-sol` / `high` | 2 / 0 | Accepted |
| Contract, integration review, production smoke, live API/browser acceptance, documentation | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

The frontend's second same-model attempt strengthened its untrusted response boundary: each citation must be unique and resolve to a stored `(page_number, block_id)` pair for the active reading. No model escalation or new package was needed.

## Verification

| Check | Observed result |
| --- | --- |
| Backend tests | 163 passed; two current third-party TestClient deprecation warnings |
| Phase 5 backend focus | 40 tests passed |
| Ruff lint and format | Passed; 38 files already formatted |
| Strict mypy | Passed: 29 application files; Phase 5 application/test check passed: 31 files |
| Dependency lock | Passed: 39 packages resolved |
| Frontend typecheck, lint and format | Passed |
| Production frontend build | Webpack build completed; route compilation, TypeScript/static generation, build ID, and a local production `200` smoke passed |
| Live API acceptance | 10 checks passed across both fictional individual crops; test documents deleted |
| Live desktop browser acceptance | 6 checks passed: availability after processing, cited direct answer, retrieval-backed answer, unavailable answer without source, removal reset, and no runtime errors |
| Live mobile browser acceptance | 3 checks passed: no horizontal overflow, Enter submission with rendered answer, and no runtime errors |

The live API exercise verified the original source licence-number answer, a provider-backed answer to **“Is LMV printed on the document?”**, a passport-number abstention, citation page/block resolution, anonymous denial, deletion, and the fact that a saved reviewer name cannot become an answer. The browser run displayed the same direct, grounded, and unavailable states on the fictional Delhi crop. These exercises use the supplied fictional examples only; they do not establish broad answer accuracy.

The local backend had to be restarted outside the development sandbox for live provider calls because a sandbox-inherited server returned the controlled `OCR_PROVIDER_ERROR` due to network restrictions. A document-free provider probe then completed, and all live document exercises passed. This was a local verification environment condition, not an application code change.

## Remaining limits

- Answers are one question at a time; there is no persistent transcript, multi-turn context, user account, audit trail, or long-term storage.
- Retrieval is bounded lexical matching over one active document. It can abstain on a paraphrase that lacks matching source terms even when a human might infer an answer.
- Source chips identify pages but do not yet open, highlight, or show answer-specific excerpts; that practical evidence navigation belongs to a later phase.
- Q&A does not use web search, reviewer edits, portraits, signatures, QR/barcode decoding, or external knowledge. It cannot prove a document is authentic.
- Browser refresh loses the in-memory document capability and transcript. Live checks cover two supplied fictional images, not varied real-world licences.
