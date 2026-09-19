# Phase 4: editable review form and durable save

Status: complete on 19 September 2026. This phase turns the Phase 3 extraction into an editable browser form and saves reviewer changes beside, never inside, the original extraction. It does not implement document Q&A or retrieval. The detailed contract is [here](PHASE_4_CONTRACT.md).

## What changed

The backend now exposes capability-protected `GET /api/documents/{id}/fields` and `PUT /api/documents/{id}/fields` routes. The first response derives a reviewed view from the immutable extraction without writing it. A save accepts one complete reviewed form, validates bounded values and exact additional-information keys, normalizes outer whitespace, derives every edited flag on the server, and atomically stores the separate review state. Original value, raw source text, warnings, and evidence never change.

The browser now runs read → extract → fields after a reviewer chooses **Read document**. It displays full name, licence number, birth/issue/expiry dates, address, vehicle classes, issuing authority, and present additional fields beside the document preview. Each source value stays visible with its page reference. The form marks local and saved corrections as user-edited, keeps unsaved changes local, supports save/retry/reset, and clears its review state on replacement or removal.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) routed both independent work units as strong-tier due to document-data integrity and response-boundary risk.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Reviewed-data models, persistence, validation and API | [7/8, high risk](routing/phase-4-backend-assessment.json) | `/root/phase4_backend`, `gpt-5.6-sol` / `high` | 1 / 0 | Accepted |
| Form integration, response validation and save interaction | [6/8, high risk](routing/phase-4-frontend-assessment.json) | `/root/phase4_frontend`, `gpt-5.6-sol` / `high` | 2 / 0 | Accepted |
| CORS integration, browser acceptance, live review exercise and reporting | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

The frontend’s second attempt tightened the untrusted response decoder: source extraction fields must retain `current_value=null` and `is_edited=false`, and returned evidence block IDs must be non-empty. The coordinator added `PUT` to CORS and created the browser/live acceptance exercises. No new dependency, provider, or AI-development tool was added.

## Verification

| Check | Observed result |
| --- | --- |
| Backend tests | 123 passed; two current third-party TestClient deprecation warnings |
| Ruff lint and format | Passed; 33 files formatted |
| Strict mypy | Passed: 26 application source files |
| Dependency lock | Passed: 39 packages resolved |
| Frontend typecheck, lint and format | Passed |
| Frontend production build | Passed with Next.js 16.3.5 |
| Offline browser acceptance | 7 checks passed: population, save, reset, failed-save retry, mobile layout, removal reset, and no runtime errors |
| Live review API acceptance | 4 checks passed on the fictional Delhi crop; test document deleted |
| Live browser acceptance | 5 checks passed on the fictional Delhi crop: populated form, save, reload/source preservation, removal, and no runtime errors |

Backend tests cover default derivation, review persistence/reload, intentional clearing, source preservation, invalid request shapes and values, capability protection, extraction prerequisite, and delete/expiry/replaced-record races. The offline browser exercise uses synthetic reading/extraction/review responses and the real local upload, preview, CORS, and deletion paths; no provider call is made there.

The live API exercise uploaded the fictional Delhi crop, completed real OCR and extraction, loaded its default review, saved a corrected name and an intentionally cleared address, reloaded the saved review, confirmed anonymous access was denied, and removed the transient document. A separate real browser run uploaded the same crop, populated the form, saved a reviewer name, verified the immutable source remained separate through the actual API, and removed its transient document. These runs confirm the supplied example path only, not broad extraction or form accuracy.

## Remaining limits

- A browser refresh still loses the in-memory document capability and therefore cannot reopen the private temporary document.
- Review state is durable only for the document’s temporary retention period. There are no user accounts, long-term data storage, audit trail, exports, or concurrent-edit conflict resolution.
- The app does not use reviewer changes as document evidence. A saved correction can differ from the source extraction, and the original page evidence remains visible.
- Document Q&A, retrieval, answer citations, and evidence navigation/highlighting remain unimplemented.
