# Phase 1 completion report

Date: 19 September 2026.

**Result: PASS. Upload and preview are complete. Phase 2 has not started.**

## Delivered behavior

The workspace accepts one PDF, PNG, JPG, or JPEG using the picker or drag-and-drop. It shows the selected filename and size, uploads it to the real API, fetches the validated original through protected access, and displays an image or native PDF preview. The UI supports pending states, useful errors, replacement, removal, and retry. It explicitly says that document reading and extraction are unavailable yet.

The backend validates the filename extension, declared MIME type, magic bytes, image decoding or PDF structure, nonempty content, and size. Defaults are 10 MiB per file, 11 MiB per multipart request, 20 PDF pages, 12,000 pixels on either image dimension, and 40 million total image pixels. Encrypted PDFs are rejected. Both declared-length and streamed requests are bounded, including the trailing-slash upload route.

Storage uses generated UUID keys under the ignored private `backend/.data/documents` directory. A generated document capability is returned only on successful creation, retained in browser memory, and stored as a hash on the backend. Existing-document operations require its bearer header; the document ID is insufficient. Responses omit storage paths, have no-store caching, and use safe error envelopes. Preview URLs are local blob URLs, with no capability in the URL.

Replacement preserves the current document when the new upload fails. Once the replacement preview is ready, the old file is removed. If cleanup fails, the UI retains the capability and offers a retry while blocking another upload that could overwrite that pending cleanup. A preview failure after a successful upload also triggers cleanup. Removal errors retain the preview and retry the removal operation. A 404 clears stale UI state with a no-longer-available message rather than claiming a successful deletion.

Access expires after 24 hours by default. Cleanup runs at startup and during document operations; expiry enforcement is independent of whether filesystem deletion succeeds. Refreshing loses the in-memory workspace access. No OCR, LLM, cloud provider, extraction, field editing, or Q&A calls were added.

## Verification

| Check | Observed result |
| --- | --- |
| Backend offline suite | **37 passed**, with two existing upstream deprecation warnings |
| Backend Ruff | Passed |
| Backend strict mypy | Passed across 19 application source files |
| Dependency lock consistency | Passed in worker verification |
| Frontend ESLint and TypeScript | Passed in worker verification; final production build also checked TypeScript |
| Frontend formatting | Passed, including the final PDF sizing change |
| Final Next.js production build | Passed; compiled and generated all four static pages |
| Live API checks | **11 passed**, including both supplied PNGs, derived JPEG/PDF, exact returned bytes, protected access, malformed/empty/oversized files, CORS, and deletion |
| Browser workflow checks | **14 passed**, including keyboard skip link, invalid selections, real PNG/JPEG/PDF upload, drag/drop replacement, preserved preview after rejection, cleanup retry, removal failure/recovery, and no runtime errors |
| Focused browser recovery checks | **4 passed**, covering failed preview cleanup, failed cleanup blocking/retry, successful recovery, and operation-specific removal retry |
| Visual review | PNG and PDF previews inspected on desktop and 390-pixel mobile viewport; no horizontal document overflow |
| Temporary upload cleanup | Final private storage contained **zero files** after test cleanup |

Browser failure checks deliberately intercepted individual requests with a temporary 503 response; they test recovery behavior, not a real provider outage. Successful uploads and protected file retrieval used the running backend. The supplied fictional licences were only used locally. JPEG/PDF fixtures were derived from the Maharashtra sample for format checks; they are not additional assessment documents or OCR results.

The initial lightweight headless browser did not paint its native PDF viewer. Full Chromium with its PDF plugin and software rendering did display the actual licence on desktop and mobile. The PDF frame height was increased for a usable preview. Native viewer support remains browser-dependent; an open-preview link is available. This does not claim that the Codex in-app browser's own PDF plugin was verified: its automation entrypoint was unavailable for this session's authentication mode. See [Playwright's browser-mode documentation](https://playwright.dev/docs/browsers).

Local verification scripts, result JSON, screenshots, process metadata, and logs are under ignored `.runtime/`. Representative screenshots are `phase1-desktop.png`, `phase1-mobile.png`, `phase1-pdf-final.png`, and `phase1-pdf-mobile.png`. They do not contain access capabilities.

## Integration findings corrected

- React development remount behavior initially disabled state updates; effect setup now resets the mounted flag.
- Response decoding now remains inside the API client's timeout and error boundary.
- Failed preview, replacement cleanup, and removal retries retain the appropriate operation and document state.
- Expired documents remain inaccessible if best-effort file cleanup fails.
- An additional coordinator check found that returning synthetic EOF at the request limit could allow a fully received multipart file to be saved before the response became 413. Overflow now aborts multipart parsing, closes parser resources, and prevents endpoint execution. The new regression covers a complete valid file followed by an oversized multipart epilogue and asserts that no storage directory is created.

## Files and responsibilities

| File or area | Change and purpose |
| --- | --- |
| `backend/app/api/documents.py` | Thin upload, metadata, file, and delete routes; exactly one multipart file; safe response headers |
| `backend/app/services/documents.py` | Validation, generated capabilities, expiry checks, and lifecycle; decode/write work runs off the async event loop |
| `backend/app/repositories/documents.py` | Private UUID storage, atomic writes, hashed capability metadata, removal and expiry cleanup |
| `backend/app/core/upload_limit.py` | Enforces declared and streamed request bounds before endpoint side effects |
| `backend/app/core/config.py` | Typed storage, retention, size, page, and pixel settings |
| `backend/app/main.py` | Wires storage, startup cleanup, document routes, and explicit CORS methods/headers |
| `backend/app/models/document.py`, `backend/app/schemas/common.py`, error handling | Upload response and document-specific controlled errors |
| `backend/tests/` | Validation, access isolation, deletion, expiry, stream bounds, and failed-write regression tests; foundation expectations updated for the new phase |
| `backend/pyproject.toml`, `backend/uv.lock` | Locked Pillow 12.3.0, pypdf 6.19.0, and python-multipart 0.0.32 |
| `frontend/src/components/document-workspace.tsx` | Accessible upload/preview workspace and bounded operation/recovery state |
| `frontend/src/lib/api-client.ts` | Generic typed request handling, bearer headers, ten-second bounds, awaited response decoding |
| `frontend/src/app/page.tsx`, `globals.css` | Connects the workspace and preserves responsive styling, with a taller PDF frame |
| `.gitignore`, `.env.example`, `README.md`, build plan and routing docs | Keeps private storage ignored and documents setup, limits, phase state, and observed verification |

## Coding-orchestrator execution

The parent invoked the actual subagent tool with explicit model and effort arguments and fresh handoffs:

- Backend: score 5/8 with high security/data risk, therefore strong; **GPT-5.6 Sol / high**. Worker reported three implementation attempts and no model escalation.
- Frontend: score 5/8, medium risk, therefore balanced; **GPT-5.6 Terra / medium**. Worker reported two implementation attempts and no model escalation.
- Coordinator: defined the shared contract, inspected both implementations, ran integrated tests, corrected the additional rejected-upload side-effect regression, and adjusted PDF frame sizing. These coordinator corrections are recorded separately rather than erasing the worker attempt history. Counting the backend integration correction with its original work unit gives four total attempts, an explicit exception to the default three-attempt workflow cap to finish the newly reproduced security fix within the authorized phase. No replacement worker or model escalation was used.

The model names above describe accepted dispatch arguments; serving internals are not independently observable. At most two workers ran concurrently. The current coordinator model was not switched. [Routing record](routing/phase-1.json).

## Environment and remaining limits

The system Node 20.11 is too old for the installed toolchain; checks used the bundled Node 24.19 runtime. A restricted-shell production build stalled. Only that verified build process was stopped, and a build with approved subprocess access succeeded; this was environment recovery, not a model escalation. The existing app backend was restarted only after its process identity was verified.

The app is a localhost demo. It has no user accounts, public deployment, aggregate storage quotas, per-user rate limits, virus scanning, encryption at rest, or isolated parser workers. Size/page/pixel bounds do not guarantee a hard CPU or memory limit for every adversarial parser input. Strict PDF checks can reject some files a forgiving reader repairs; structural validity does not prove visual fidelity or authenticity.

Cleanup does not run while the API is stopped. Corrupt metadata or a crash between the byte write and metadata publication can leave unaddressable orphan files for operator cleanup. Storage is temporary, and reviewed-data persistence belongs to a later phase.

## Handoff

- Application: [http://127.0.0.1:3000](http://127.0.0.1:3000).
- API health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).
- Both development services remain running. No commits, pushes, deployment, or external AI calls were made.
- Next authorized work can be Phase 2 document reading/OCR; it has not started.

Implementation references: [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [Pillow image loading and validation](https://pillow.readthedocs.io/en/stable/reference/Image.html), and [pypdf reader behavior](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html).
