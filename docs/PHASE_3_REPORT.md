# Phase 3: structured licence extraction

Status: complete on 19 September 2026. This phase adds a private, evidence-backed extraction API. It does not render a review form, persist human edits, or answer document questions; those scopes remain in later phases. The detailed contract is [here](PHASE_3_CONTRACT.md).

## What changed

`POST /api/documents/{id}/extract` takes an already saved reading and returns cached, nullable licence fields. `GET /api/documents/{id}/extraction` retrieves that result. Both require the document's bearer capability and return `Cache-Control: no-store`.

The OpenAI adapter receives only page/block text from the private reading cache. It uses one Responses API call with a strict JSON schema, no tools, no automatic SDK retries, and `store=False`. It returns candidate values plus block IDs, never final evidence. The service resolves block IDs against its own stored reading, keeps their page order, and exposes a field only when both its candidate value and raw value are supported by the cited text. Unknown IDs, cross-document IDs, and malformed candidates fail safely. Unsupported individual fields become null with warnings.

The extraction result is immutable and cached with the private document. Duplicate extraction calls are deduplicated, results cannot be published after deletion or expiry, and a multi-licence result suppresses every field instead of merging holders. `current_value` remains null and `is_edited` false for every extracted field because editing belongs to Phase 4.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) assessed both work units as strong-tier because incorrect grounding could expose unsupported document facts.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Extraction models, cache, API and grounding validation | [7/8, high risk](routing/phase-3-backend-assessment.json) | `/root/phase3_backend`, `gpt-5.6-sol` / `high` | 2 / 0 | Accepted |
| OpenAI structured-output protocol and adapter | [6/8, high risk](routing/phase-3-provider-assessment.json) | `/root/phase3_provider`, `gpt-5.6-sol` / `high` | 1 / 0 | Accepted |
| Integration, evidence review, live acceptance and reporting | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

The backend's second attempt corrected deep immutability: Pydantic frozen models alone do not freeze contained lists and dictionaries, so evidence, warnings, vehicle classes, and additional-information mappings now use immutable containers while serializing as the same JSON arrays and object. Coordinator verification also applied the repository formatter to four new files after its format gate reported only mechanical changes. OpenAI's [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) informed the strict JSON response format. Langfuse evaluation guidance was used only to keep the local sample expectations separate from accuracy claims; no Langfuse project, trace, prompt, or dataset was created.

## Verification

Offline checks completed after the final formatting pass:

| Check | Observed result |
| --- | --- |
| Backend tests | 100 passed; two third-party deprecation warnings from the current FastAPI/Starlette test client stack |
| Ruff lint | Passed |
| Ruff format | 31 files already formatted |
| Strict mypy | Passed: 25 application source files |
| Dependency lock | Passed: 39 packages resolved |

The mocked tests cover capability and read prerequisites, cache retrieval, duplicate-call suppression, process capacity, provider failures and timeouts, oversized input, unsupported values, malformed/unknown/cross-document block IDs, multi-licence suppression, extra-field naming, blank pages, and deletion/expiry races. Provider tests exercise the SDK request shape and error handling without a live key.

The live API exercise used the two supplied fictional crops with the configured local OpenAI credential. It uploaded, read, extracted, retrieved a cached result, rejected an unauthenticated retrieval, and deleted each test document. Both runs returned `EXTRACTED` with no top-level warnings:

| Sample | Selected fields checked | Vehicle classes checked | Stored reading blocks |
| --- | --- | --- | --- |
| Maharashtra | Name, licence number, birth/issue/expiry dates, address fragment, issuing authority | LMV, MCWG | 31 |
| Delhi | Name, licence number, birth/issue/expiry dates, address fragment, issuing authority | LMV, MCWG | 20 |

For every selected non-null field, the exercise checked that the returned evidence referenced the same document and exactly matched a stored source block and page. It is a demonstration on the supplied samples, not a broad extraction benchmark or human-approved ground truth. The transient test documents were deleted after the run.

## Remaining limits

- The frontend still does not call extraction or display/edit its fields. That is Phase 4 work.
- There is no durable reviewed-data store, account authentication, deployment hardening, or cross-process job coordination.
- Vision OCR and structured extraction can still misread unfamiliar layouts, low-quality scans, handwritten text, or languages outside the examples. Evidence grounding prevents unsupported output from being displayed but cannot guarantee the OCR source itself is correct.
- The composite sample has not been used for a live extraction request. Offline coverage verifies suppression when the provider detects multiple licences; the product continues to ask for one licence per upload.
- Document Q&A, retrieval and answer citations remain unimplemented.
