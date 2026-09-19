# Phase 0 completion report

Date: 19 September 2026.

**Result: PASS. Phase 0 is complete. Phase 1 has not started.**

## Delivered behavior

The initial LicenceIQ workspace runs locally with a responsive, restrained interface, an explicitly disabled upload placeholder, and an empty information preview. In development, a browser request to the FastAPI health endpoint drives the connection indicator. An unavailable backend produces a useful status and Retry button. Production frontend output omits that development indicator.

The backend provides `GET /health`, typed environment configuration, explicit CORS origins, request IDs, sanitized exception handling, and initial document/evidence models. It makes no external provider calls and does not read or upload licence files.

## Acceptance criteria

| Criterion | Result | Evidence |
| --- | --- | --- |
| Frontend starts | PASS | Local development app opened in the Codex browser at `http://127.0.0.1:3000` |
| Backend starts | PASS | Uvicorn started on `127.0.0.1:8000`; live GET returned `{"status":"ok"}` |
| Frontend calls health successfully | PASS | Browser displayed Backend connected; frontend/backend use separate local ports |
| Type checking passes | PASS | Frontend route generation + `tsc --noEmit`; backend mypy reported no issues in 15 source files |
| Linting passes | PASS | Frontend ESLint with zero permitted warnings; backend Ruff |
| Basic backend test passes | PASS | 13 offline backend tests passed |

Additional verification:

- Next.js production build passed: compilation, TypeScript, and static page generation.
- Prettier check passed for frontend source and configuration.
- npm dependency audit reported zero vulnerabilities at installation time. This is a point-in-time dependency result, not a comprehensive security audit.
- Desktop viewport 1440 x 1000: two-column workspace, no horizontal overflow.
- Mobile viewport 390 x 844: stacked workspace, no horizontal overflow, including the backend-unavailable state.
- Upload button was disabled in both development and production.
- The skip link received keyboard focus with a visible outline and activated the workspace anchor.
- A temporary production server on port 3001 showed no development connection badge.
- For failure/recovery, only this task's backend was stopped. The page displayed Backend unavailable. After restarting it, clicking Retry restored Backend connected.
- Browser error/warning inspection was empty before the deliberate backend-outage test. Connection-refused errors during that deliberate test were expected.
- Browser viewport overrides were reset after testing; the working development tab was kept open.

## Architecture decisions

1. The existing workspace root is the project root, with separate `frontend/` and `backend/` directories. Existing plan and sample files were preserved.
2. FastAPI uses an application factory. HTTP routes remain thin; service, provider, repository, and prompt packages are reserved without premature implementation.
3. Pydantic models define the initial document contract. Matching TypeScript types retain the same wire names. There is no ORM or database in Phase 0.
4. Extracted fields distinguish original values, raw values, evidence, reviewed values, and edit flags. Actual editing and saving are future work.
5. The frontend uses one API client for timeouts, cancellation, safe errors, and response validation.
6. CORS is limited to configured origins and the currently implemented GET method. It is not presented as authorization.
7. Unexpected failures are caught inside the CORS layer so the browser can read the sanitized error and raw exception details do not reach Uvicorn's error logger through ordinary route failures.
8. Fonts are installed locally. The app does not rely on a runtime Google Fonts request.
9. No shadcn/ui dependency was needed for this static shell; no upload, form, OCR, LLM, or retrieval packages were added.
10. Turbopack is explicitly rooted at the frontend directory to avoid an unrelated ancestor lockfile affecting project discovery.

## Files created or changed

| Files | Responsibility and important functions |
| --- | --- |
| `.gitignore` | Excludes credentials, dependencies, caches, generated builds, runtime logs, and future private storage |
| `.env.example` | Documents backend settings without secrets |
| `README.md` | Stack, architecture, setup, environment variables, checks, planned AI approach, limitations, and actual AI development tools used |
| `LICENCEIQ_BUILD_PLAN.md` | Updates milestone status while preserving later-phase planning |
| `backend/pyproject.toml`, `backend/uv.lock` | Isolated, reproducible Python dependencies and test/lint/type configuration |
| `backend/app/main.py` | `create_app()` composes configuration, routes, handlers, and middleware; `correlate_request()` creates a request ID and contains unexpected route failures |
| `backend/app/core/config.py` | `Settings` defines typed configuration; `validate_origins()` rejects wildcard, credential-bearing, and path-based origins; `get_settings()` caches process settings |
| `backend/app/core/errors.py` | `ApplicationError` carries deliberate public errors; `error_response()` creates the envelope; `unexpected_error_response()` logs safe metadata; `register_error_handlers()` installs framework and service error handlers |
| `backend/app/api/health.py` | `health()` returns the exact liveness contract with no storage/provider dependency |
| `backend/app/schemas/common.py` | Typed health response, error codes, error detail, and error envelope |
| `backend/app/models/document.py` | `ProcessingStatus`, `Document`, `DocumentPage`, `Evidence`, `ExtractedField`, and `ExtractedLicence`; no sample values or processing logic |
| `backend/app/**/__init__.py` | Package boundaries and concise explanations; future service/provider/repository/prompt packages remain empty |
| `backend/tests/test_foundation.py` | 13 tests: health/correlation, CORS success/rejection/preflight, absent upload route, controlled/unexpected/validation errors, origin validation, nullable independent field defaults, one-based evidence pages |
| `frontend/package.json`, `frontend/package-lock.json` | Frontend dependencies, compatible Node engines, and run/check/format scripts |
| `frontend/.env.example` | Public backend URL configuration |
| `frontend/tsconfig.json`, `frontend/next-env.d.ts` | Strict TypeScript and framework-generated type references |
| `frontend/next.config.ts` | Next.js application settings, disabled framework dev overlay indicator, explicit Turbopack root |
| `frontend/postcss.config.mjs` | Tailwind PostCSS integration |
| `frontend/eslint.config.mjs` | Next.js and TypeScript lint rules |
| `frontend/.prettierignore` | Keeps generated declarations, lockfile, build output, and dependencies out of formatting |
| `frontend/src/app/layout.tsx` | Root metadata, language, local fonts, and global styles |
| `frontend/src/app/page.tsx` | `Home()` renders the honest empty workspace, upload placeholder, planned workflow, and development-only status |
| `frontend/src/app/globals.css` | Semantic visual tokens, component states, desktop/mobile layout, reduced-motion handling, and keyboard focus styles |
| `frontend/src/app/icon.svg` | Project favicon |
| `frontend/src/components/icon.tsx` | `Icon()` supplies a small local set of decorative SVG icons |
| `frontend/src/components/backend-status.tsx` | `BackendStatus()` checks the real API, handles cancellation, and exposes Retry on failure |
| `frontend/src/lib/env.ts` | `apiBaseUrl()` validates public URL settings; `publicEnv` keeps developer display conditions separate |
| `frontend/src/lib/api-client.ts` | `ApiError`, `request()`, and `getHealth()` centralize typed, bounded API access |
| `frontend/src/types/document.ts` | Matching frontend document and evidence contracts |
| `frontend/AGENTS.md`, `frontend/CLAUDE.md` | Generated by Next.js development tooling; these do not indicate Claude was used |
| `docs/PHASE_0_REPORT.md` | This acceptance and implementation report |

No Git repository was initialized, and no commits or pushes were made. The existing sample images were not changed during Phase 0. Local environments, installed dependencies, logs, and build outputs are generated artifacts rather than source deliverables.

## Commands run

Backend setup and checks, from `backend/`:

```powershell
uv sync --python 'C:\Program Files\Python311\python.exe' --cache-dir '..\.cache\uv'
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests --no-cache
.\.venv\Scripts\python.exe -m mypy app
```

The successful frontend checks invoked the installed tools directly with Node.js 24.19.0, equivalent to these package scripts from `frontend/`:

```powershell
npm.cmd run format
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run format:check
```

The actual compatible runtime used in this environment was:

```text
C:\Users\aksha\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe
```

For an exact rerun of a check with that existing runtime:

```powershell
# From frontend/
$phaseNodeDirectory = 'C:\Users\aksha\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'
$env:PATH = $phaseNodeDirectory + ';' + $env:PATH
& (Join-Path $phaseNodeDirectory 'node.exe') .\node_modules\eslint\bin\eslint.js . --max-warnings=0
& (Join-Path $phaseNodeDirectory 'node.exe') .\node_modules\next\dist\bin\next typegen
& (Join-Path $phaseNodeDirectory 'node.exe') .\node_modules\typescript\bin\tsc --noEmit
& (Join-Path $phaseNodeDirectory 'node.exe') .\node_modules\next\dist\bin\next build
```

Dependency installation used the npm CLI with a project-local cache. Initial restricted-shell Node checks were interrupted and rerun outside that shell; they are not counted as passes. An optional lockfile-only refresh encountered npm's remote-fetch restriction, so only the already-installed root engine metadata was synchronized directly. No dependency tarball URL or integrity value was changed manually.

The backend and frontend were launched as hidden local processes for live checks. The temporary production preview was stopped after its check. Process metadata and logs are under ignored `.runtime/`.

## Known issues and limits

- Python tests emit two upstream deprecation warnings from Starlette's test client: its legacy httpx fallback and AnyIO BlockingPortal alias. All 13 tests pass; the warnings are recorded rather than suppressed.
- The installed Next.js lint plugins currently declare ESLint 9 support. ESLint 9's installer reports end-of-support; upgrading to ESLint 10 would conflict with those plugin peer ranges. No dependency vulnerability was reported by npm audit. Revisit together with compatible plugin updates.
- npm 12 reported a blocked optional `unrs-resolver` postinstall. Its Windows native package was already installed; lint and the production build passed without enabling the blocked script.
- The system Node.js 20.11 is older than the complete toolchain's engine requirements. Use Node.js 22.13+ LTS or 24 LTS; the verified build used 24.19.0.
- Upload, document parsing, OCR, extraction, editable forms, persistence, RAG, Q&A, citations, authentication, and deployment are intentionally absent.
- The backend health check is process liveness only. The running app is local to this machine, not a deployed submission URL.
- No live AI requests or assessment-sample OCR checks were made.

## Handoff

Development app: `http://127.0.0.1:3000`.

Backend health: `http://127.0.0.1:8000/health`.

Both were left running at handoff. Phase 1 can add validated document upload and preview when requested. Do not interpret Phase 0 completion as completion of the assessment application.
