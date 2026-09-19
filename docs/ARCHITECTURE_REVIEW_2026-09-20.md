# Senior engineering review — 20 September 2026

## Verdict

LicenceIQ is a strong technical-assessment submission. Its API/service/provider/repository separation is clear, the document and evidence lifecycle is unusually well defended for the scope, and the application meets the requested upload, OCR, structured review, grounded Q&A, and source-verification flow.

No P0 finding was identified. Before an interview submission, fix the two Q&A correctness defects, prevent accidental loss of unsaved reviewer edits, and give the user a complete OpenAI disclosure. Before any public deployment, complete the security and operations backlog rather than treating the current bootstrap/JWT setup as a user-account system.

## Review scope

The review covered the 148 non-generated repository files, grouped by their responsibility:

| Area | Files reviewed | Result |
| --- | --- | --- |
| Application composition and API | `backend/app/main.py`, `backend/app/api/*`, `backend/app/core/*`, schemas | Clear composition, controlled errors, bounded upload path. |
| Document lifecycle and storage | `backend/app/services/documents.py`, `reading.py`, `extraction.py`, `review.py`, `questions.py`, repositories | Strong single-process lifecycle controls; several correctness and production lifecycle gaps. |
| OpenAI boundaries | `backend/app/providers/*`, prompts, model contracts | Good input/output bounds, `store=False`, provider error sanitisation, and prompt-injection resistance. |
| Browser flow | `frontend/src/app/*`, components, libraries, types, configuration | Strong runtime decoding and in-memory credentials; destructive-state and test gaps remain. |
| Quality and delivery | backend tests, frontend package/configuration, environment samples, README and phase documents | Excellent backend coverage; no frontend behavioral test suite or CI workflow. |
| Historical planning records | `docs/PHASE_*`, `docs/routing/*`, submission/demo documents | Good traceability; retain as evidence rather than adding more phase history to the README. |

## Must fix for the assessment

### P1 — Q&A can return a wrong name

`[backend/app/services/questions.py](../backend/app/services/questions.py)` line 191 treats the generic phrase `name` as a request for the licence holder's name. A question such as “What is the father name?” can therefore return the holder's name instead of abstaining or retrieving the relationship field.

This violates the assessment requirement that unavailable information must not be invented. Remove the bare `name` trigger, use explicit holder-name phrases, and match father/mother/spouse/guardian questions against `other_information`. Add regression tests for holder name, father name, and multi-intent questions.

### P1 — A valid citation does not prove the answer

`[backend/app/services/questions.py](../backend/app/services/questions.py)` lines 466–509 verify that cited IDs exist in the retrieved blocks, but they do not verify that an answer is supported by those blocks. The provider can return an invented value with a real, unrelated citation and the system accepts it.

For this assessment, make broad answers extractive: require the model to return an exact supporting quote or value with its block IDs, and verify it deterministically against those cited blocks. If verification fails, return the existing unavailable response. Add an adversarial test for a fabricated answer with a valid but unrelated citation.

### P1 — Unsaved corrections can be discarded

`[frontend/src/components/document-workspace.tsx](../frontend/src/components/document-workspace.tsx)` calculates `hasUnsavedChanges` at lines 1314–1319, but replacement and removal remain available at lines 1472–1527. Both clear local review state.

Require an explicit discard confirmation, or disable replace, remove, sign-out, and guest exit while the review form is dirty. This protects the reviewer’s manual corrections, which are central to the requested workflow.

### P1 — The provider disclosure is incomplete

The browser text at `[frontend/src/components/document-workspace.tsx](../frontend/src/components/document-workspace.tsx)` lines 1533–1536 says scanned-image reading uses OpenAI. In practice the application also sends extracted text for structured extraction, embeddings, and broader Q&A.

Before upload, clearly disclose that document images or text and questions can be sent to OpenAI for the requested processing, that temporary storage expires, and that Remove attempts deletion. This is a product/privacy expectation for licence data.

### P1 — Add focused browser tests

`[frontend/package.json](../frontend/package.json)` has lint, type, format, and build checks but no behavior tests. Add a small Vitest/React Testing Library suite for credential headers, dirty-state transitions, expiry/401 behavior, partial processing failure, and cleanup. Add one Playwright happy-path smoke test with provider stubs.

## Fix before any deployment

| Priority | Finding | Why it matters | Recommended change |
| --- | --- | --- | --- |
| P1 | Production accepts `minio_secure=false` in `[backend/app/core/config.py](../backend/app/core/config.py)` lines 142–150. | Licence files and object-store credentials could travel over plaintext transport. | Reject production configuration unless `LICENCEIQ_MINIO_SECURE=true`; add a settings test. |
| P1 | Login, review, and question JSON bodies have no explicit size limit, and request parsing can precede authorization. | A public API can waste memory and Argon2 CPU before deciding a caller is authorized. | Apply bounded JSON body limits, authorize first where possible, and add IP/account rate limiting. |
| P1 | Expired document deletion runs only at startup and application activity. | Idle PII remains beyond the advertised retention period; corrupt metadata can orphan content. | Add scheduled cleanup, MinIO lifecycle rules, orphan reconciliation, deletion metrics, and an audit record. |
| P1 | PDFs with a small native-text layer can skip OCR even when fields are visibly scanned. | Important licence fields can be missed. | Add a mixed text/image PDF fixture and OCR fallback or merge based on coverage/confidence. |
| P1 | Persisted metadata has no model-level invariant tying nested reading, extraction, index, and review IDs to the enclosing document ID. | Corrupt sidecar metadata may be internally inconsistent. | Add record validators for canonical IDs, nested document IDs, page count, and owner/capability invariants; quarantine bad records. |
| P2 | Filesystem and MinIO locks are single-process only; MinIO uses read-modify-write. | Multiple workers can overwrite lifecycle changes. | Use a metadata database or conditional ETag/version writes before horizontal scaling. |
| P2 | The expiry scan is O(all documents) on every authorized request. | Storage latency grows with document count, especially in MinIO. | Run indexed/scheduled expiry cleanup rather than request-path scans. |
| P2 | PDF parsing happens inside the API process. | Hostile or pathological files can consume CPU/memory despite size checks. | Add malware scanning and an isolated parser/worker with resource limits. |
| P2 | There is no readiness endpoint, privacy-safe metrics, audit trail, or incident observability. | Operations cannot distinguish a live API from a usable document service. | Add `/ready`, storage/config checks, structured metrics/traces, and privacy-preserving audit events. |
| P2 | The JWT bootstrap account has no revocation, recovery, document listing, or reopen flow. | It is correct for a demo but insufficient for a real account system. | Move to OIDC (Keycloak + Auth.js + FastAPI JWKS validation) with a metadata database. |

## Browser and interaction risks

- The pipeline commits the new reading before extraction and review are both available at `[document-workspace.tsx](../frontend/src/components/document-workspace.tsx)` lines 1140–1168. Keep the complete result in local variables and commit it atomically; clear or version chat/source state on reprocessing.
- Leaving a hybrid guest workspace at `[auth-gate.tsx](../frontend/src/components/auth-gate.tsx)` lines 142–151 discards the only capability while retaining the server copy until expiry. Confirm the action and attempt deletion before losing the capability.
- A generic 404 on read/save/Q&A does not clear stale local document state. Centralise expired-document handling and offer a clear restart path.
- Frontend and backend auth mode alignment is manual. Expose a non-secret server capability/mode response so a mismatch is reported clearly rather than failing later on a document request.
- The 2,000-line document workspace should be split into API calls, runtime schemas, lifecycle/state management, preview, review, and Q&A modules. Use a discriminated props union so invalid access-mode/token combinations cannot be represented.
- Add CSP, `nosniff`, referrer, permissions, and frame-ancestor headers before deployment. Treat PDF preview sandboxing or server-rendered preview as a production hardening item.

## What is already strong

- Uploads have streamed request limits, extension/MIME/content validation, image/page bounds, generated storage keys, safe downloads, and temporary retention.
- Guest document capabilities are high entropy, stored only as hashes server-side, and isolated from JWT ownership in hybrid mode. Invalid JWTs do not fall back to guest access.
- The original extraction, reviewer correction, page evidence, semantic index, and citations are separated instead of overwriting one another.
- Provider calls use bounded input/output, explicit timeouts, `store=False`, sanitised errors, no tool calls, and prompts that treat document content as untrusted evidence.
- Backend coverage is unusually comprehensive for the timebox: 228 offline tests currently pass. Current checks also pass Ruff, formatting, strict mypy, ESLint, TypeScript, Prettier, and production frontend builds in capability, hybrid, and JWT modes.

## Failure scenarios to design and test next

| Scenario | Expected behavior | Test type |
| --- | --- | --- |
| “Father name?” is absent | Grounded unavailable response, never holder name. | Unit/service regression |
| Answer cites a real but unrelated line | Reject candidate and abstain. | Adversarial provider test |
| Extraction provider times out after reading | Preserve the last complete UI snapshot; show a retryable, safe error. | Frontend integration |
| Reviewer replaces/removes a dirty form | Confirmation before losing edits. | Frontend interaction |
| Guest leaves workspace accidentally | Confirm and delete or keep recoverable access during the session. | Frontend interaction |
| Document expires while open | Clear stale preview/form/chat and offer a clean restart. | Browser/API integration |
| Corrupt or mismatched metadata | Treat as unavailable; quarantine/reconcile content without exposing it. | Repository test |
| Idle service crosses retention limit | Scheduled job/lifecycle rule removes bytes and metadata. | Infrastructure integration |
| Multiple workers update the same document | Conditional write detects conflict and safely retries/returns a controlled state. | Storage integration |

## Recommended implementation order

1. Correct direct Q&A intent resolution and answer-to-citation verification, with the two adversarial tests.
2. Add discard protection, complete provider disclosure, and the focused frontend regression suite.
3. If deployment is in scope, enforce TLS MinIO, bounded JSON/rate limits, scheduled deletion, and readiness/observability.
4. For a real product, add OIDC, persistent metadata, safe multi-worker coordination, isolated parsing, and user document recovery.

The first two steps strengthen the assessment result without turning its 48-hour scope into an unnecessary production platform.
