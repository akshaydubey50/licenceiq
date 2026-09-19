# Phase 2 implementation and verification

Status: complete on 19 September 2026. Authorized scope is page-level reading and OCR only; see [contract](PHASE_2_CONTRACT.md). Structured extraction, editable fields and Q&A remain later phases.

## Provider decision

The user selected OpenAI for OCR and future LLM calls. The root `.env` contains a locally entered `OPENAI_API_KEY`; no credential is in source, frontend or this report. API access was verified through the app. Default OCR model is configurable `gpt-4.1-mini`. Native PDF text does not require a key. Local RapidOCR was considered before the user's provider selection; an unsuccessful dependency trial installed nothing and that approach was not implemented.

## Actual routing

| Work unit | Assessment | Actual execution | Attempts / escalations |
| --- | --- | --- | --- |
| Page pipeline, private cache, read routes and lifecycle tests | 6/8, high-risk, strong | `phase2_backend`, `gpt-5.6-sol` / `high` | 2 / 0; accepted |
| Read controls, page inspector and response validation | 4/8, medium-risk, balanced | `phase2_frontend`, `gpt-5.6-terra` / `medium` | 2 / 0; accepted |
| OpenAI adapter, configuration, dependency lock and transport tests | 4/8, high-risk, strong recommendation | Direct coordinator execution; coordinator model unchanged | 1 / 0 |

Both workers were actually dispatched with explicit supported models and no nested delegation. Their file ownership is separate. Helper inputs and recommendations are in `docs/routing/phase-2-*-assessment.json` and `phase-2-*-recommendation.json`. The coordinator owns integration review and final verification.

Backend correction 2 restored retryable content-first deletion under the repository lock, bounded PDFium lock waiting and integer raster rounding, and froze source-evidence models. Frontend correction 2 tightened confidence/box/block/page validation and cleared stale failed-operation state on new file selection. Both retained their original model/effort; no escalation was needed. Installation permissions and a browser-test whitespace assertion were environment/harness issues, not model failures.

## Changed responsibilities

| Files | Purpose |
| --- | --- |
| `backend/app/providers/ocr.py`, `openai_ocr.py` | Provider-neutral OCR result/protocol and a bounded, sanitized OpenAI image transcription adapter |
| `backend/app/core/config.py`, `backend/pyproject.toml`, `backend/uv.lock`, `.env.example` | Secret backend configuration, image/time/text limits and reproducible SDK/rendering dependencies |
| `backend/app/services/reading.py` | Native text selection, image preparation, PDF rendering, page evidence, deadlines, four concurrent reading slots and duplicate suppression |
| `backend/app/repositories/documents.py`, `services/documents.py` | Private inline reading cache, shared lifecycle lock, capability checks, conditional publication and retryable deletion |
| `backend/app/models/document.py`, `schemas/common.py` | Frozen page evidence/readings and controlled errors |
| `backend/app/main.py`, `api/documents.py` | Provider injection, read/retrieve HTTP routes and private responses |
| `backend/tests/test_openai_ocr.py`, `test_reading.py` | 16 real-SDK offline transport checks and 13 pipeline/lifecycle checks |
| `frontend/src/components/document-workspace.tsx`, `lib/api-client.ts`, `types/document.ts`, `app/globals.css` | Explicit read action, matching validated response types, read timeout, safe development inspector and responsive states |

## Verification

- OpenAI SDK 2.54.0 and pypdfium2 5.13.0 installed in the project environment and locked.
- 16 adapter tests pass using the real OpenAI SDK with an offline HTTP transport: image input, strict output shape, no response storage/tools/retries, absent key, malformed output, refusal, truncation, provider errors, timeout, empty transcription and secret configuration.
- All 66 backend tests pass, including the prior 37 foundation/upload tests. New pipeline tests cover native PDFs without OCR, cache persistence across app recreation, prepared image/scanned PDFs, mixed page methods, blank text, output size, provider failures without partial publication, capability denial before provider use, concurrent duplicate suppression, deletion/expiry during OCR and retryable file removal.
- Ruff checks and formatting pass; strict mypy passes for 22 app files. Dependency lock check passes (39 packages). Two upstream Starlette/httpx/AnyIO deprecation warnings remain; they do not fail the suite.
- Frontend formatting, ESLint, Next type generation, TypeScript and production build pass using Node 24.19.
- 12 offline browser scenarios pass: no automatic paid reading on upload; busy/error handling; rejected cross-document, invalid-confidence, invalid-box, duplicate-block and wrong-page-count responses; retry/warnings/literal text rendering; mobile layout; replace/remove resets; no runtime errors. These tests intercept every read call and use synthetic text.
- The production frontend was started temporarily on port 3002. A mocked successful upload/read confirmed that the raw page inspector and development health status are absent. That temporary server was stopped afterward.

## Live fictional sample acceptance

Both samples passed actual browser upload -> OpenAI OCR -> page text display. Each returned one `ocr` page with `READ` status. Selected visible strings were compared after ignoring case, punctuation and spacing:

| Document | Checked visible token groups | Observed output |
| --- | --- | --- |
| Maharashtra crop | Name, licence number, DOB, issue date, expiry date, LMV, MCWG, issuing authority, address fragment: 9/9 found | 24 blocks, 526 characters |
| Delhi crop | Same nine token groups: 9/9 found | 18 blocks, 468 characters |

The browser also verified protected result retrieval, an identical cached POST result, blank structured fields, responsive mobile display, deletion and no runtime errors. Desktop and mobile screenshots were visually inspected. Each test upload and its reading was deleted; the private document directory was empty after verification. The development frontend (3000) and updated backend (8000) remain available.

This is evidence for the two supplied fictional examples, not a full transcription accuracy score, broad benchmark or human-approved ground truth. Live scanned-PDF OCR was not separately charged/tested; rendering and the scanned/mixed pipeline were tested offline with provider substitutes. Portraits, signatures and QR contents were not evaluated.

Local ignored evidence: `.runtime/phase2-browser-offline-results.json`, `phase2-live-results.json`, `phase2-production-result.json` and `phase2-live-*.png`. No tokens or API keys are written into these reports.

## Limits and next phase

- Native text suitability uses a documented heuristic; an incomplete but long text layer can evade OCR fallback.
- One backend process is supported. In-process parsing cannot be forcibly interrupted, and this localhost assessment app does not include public-service quotas or isolated parser workers.
- OpenAI output can contain OCR mistakes. Confidence/boxes remain null instead of manufacturing certainty. `store=False` is used, but does not imply zero provider retention; see [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).
- The whole assessment is not complete. Phase 3 should turn page evidence into validated licence fields. No structured extraction, review saving or Q&A was implemented in Phase 2.

Official references checked during implementation: [image inputs](https://developers.openai.com/api/docs/guides/images-vision), [structured output](https://developers.openai.com/api/docs/guides/structured-outputs), [model capabilities](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [PDFium threading constraints](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading). Langfuse prompt/evaluation skill guidance was used locally; no Langfuse telemetry or live dataset was created.
