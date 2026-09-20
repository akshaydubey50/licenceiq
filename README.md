# LicenceIQ

LicenceIQ is an AI document-intelligence workspace for driving licences. A reviewer uploads one licence, reads it, checks evidence-backed extracted data, edits the reviewed record when necessary, and asks grounded questions about the same document.

The supplied Maharashtra and Delhi images are fictional test samples. LicenceIQ does not determine whether a licence, identity, signature, portrait, or QR code is genuine.

## Project overview

The complete user flow is:

```text
Upload driving licence
  -> Read native text or OCR a scanned page
  -> Extract structured, source-backed fields
  -> Auto-populate an editable review form
  -> Save reviewer corrections separately
  -> Ask grounded questions about the active document
  -> Open the cited page and evidence excerpt
```

The local application supports one licence per upload. It intentionally refuses to merge information when a file appears to contain multiple licence holders.

## Features

| Requirement | LicenceIQ behavior |
| --- | --- |
| Upload and preview | Accepts PDF, PNG, JPG, and JPEG files up to 10 MB. The backend validates type, structure, dimensions/pages, and content before storing a private temporary copy. |
| OCR and document reading | Uses native PDF text when readable. For image licences and scanned PDF pages, it renders a bounded image and uses OpenAI vision OCR. |
| Structured extraction | Extracts name, licence number, date of birth, issue/expiry dates, address, vehicle classes, issuing authority, and other directly supported fields. |
| Human review | Auto-populates an editable form. A saved review value remains separate from the original extraction and its source evidence. |
| Ask the document | Answers known field questions directly. For broader questions, it retrieves evidence only from the active document and returns an answer with citations or an explicit unavailable response. |
| Source verification | Opens the cited page and displays the exact stored evidence excerpt for fields and answers. |
| Safety and errors | Keeps provider keys server-side, returns controlled errors, expires temporary data, and never treats document text as instructions. |

## Technology stack

| Area | Technology |
| --- | --- |
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI, Pydantic, pydantic-settings, Uvicorn |
| File processing | python-multipart, Pillow, pypdf, pypdfium2 |
| AI | OpenAI Responses API with `gpt-4.1-mini` for vision OCR, extraction, and grounded answers; `text-embedding-3-small` for semantic retrieval; optional local NeMo Guardrails policy checks for Q&A; optional privacy-safe Langfuse operation telemetry |
| Storage and access | Private filesystem demo profile; durable profile with MinIO for original bytes and PostgreSQL/pgvector for metadata, evidence, vectors, principals, and revocable JWT sessions |
| Quality checks | pytest, Ruff, mypy, ESLint, TypeScript, Prettier, Next.js production build |

## Architecture

```mermaid
flowchart LR
    UI[Next.js review workspace] --> API[FastAPI API]
    API --> Store[Private document repository]
    API --> Reader[Reader]
    Reader --> Native[Native PDF text]
    Reader --> OCR[OpenAI vision OCR]
    Native --> Evidence[Page text and evidence blocks]
    OCR --> Evidence
    Evidence --> Extract[Structured extraction]
    Extract --> Validate[Local evidence validation]
    Validate --> Review[Editable reviewed record]
    Evidence --> Retrieval[Same-document hybrid retrieval]
    Review --> UI
    Retrieval --> Answer[Grounded answer with citations]
    Answer --> UI
```

LicenceIQ is a modular monolith. API routes remain thin, services own business rules, repositories handle private persistence, and provider adapters isolate OpenAI-specific behavior. This keeps the assessment application understandable without adding a queue, vector database, or microservice platform.

## Setup and run locally

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22.13+ LTS or Node.js 24 LTS with npm
- An OpenAI API key for OCR, extraction, and document Q&A

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local
```

Set `OPENAI_API_KEY` in the ignored root `.env` file. Do not commit or share that file.

Start the backend in one terminal:

```powershell
cd backend
uv sync --frozen --python 3.11
.\scripts\start-local.ps1
```

The launcher makes a short, document-free OpenAI request before starting the API. It confirms that the local process can reach the configured OCR model and stops before uploads are accepted when the key, model, quota, or outbound network access is unavailable. It never sends a licence page or prints the API key. Use `-SkipOpenAIProbe` only when you deliberately want to run the UI without AI processing.

Run this script from a normal local PowerShell terminal. A restricted sandbox or container may block outbound OpenAI access; the preflight then fails clearly instead of leaving a backend that reports a generic OCR error later.

Start the frontend in another terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The development header should show **Backend connected**. Use one fictional individual sample from [`samples/`](samples/) to test the full workflow.

The copied environment files run the original no-login local demo. To show both **Continue as guest** and account access, complete the protected-mode setup in the [guest and JWT guide](docs/PHASE_9_LOCAL_SETUP.md), then set both `LICENCEIQ_AUTH_MODE` and `NEXT_PUBLIC_AUTH_MODE` to `hybrid`. The same guide explains the opt-in, local-only sign-up flow.

- API health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Development API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Run the full Docker stack

Docker Compose runs the frontend, FastAPI API, PostgreSQL with pgvector, and private MinIO together. The backend applies migrations, uses a bucket-scoped MinIO application account, and runs the document-free OpenAI preflight before it accepts uploads.

Keep the ignored root `.env` for application settings and `OPENAI_API_KEY`. Keep the ignored `infra/.env` for PostgreSQL and MinIO credentials; add the separate `LICENCEIQ_MINIO_APP_ACCESS_KEY` and `LICENCEIQ_MINIO_APP_SECRET_KEY` values from [the template](infra/.env.example) if they are not already present.

```powershell
docker compose --env-file .env --env-file infra/.env up -d --build --wait
docker compose --env-file .env --env-file infra/.env ps
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). Container ports bind only to `127.0.0.1`; MinIO stays at `127.0.0.1:9000` and its console at `127.0.0.1:9001`.

For later starts with no configuration change, use:

```powershell
docker compose --env-file .env --env-file infra/.env up -d --wait
```

After changing `.env` or application code, rebuild the affected image:

```powershell
docker compose --env-file .env --env-file infra/.env up -d --build --wait
```

`docker compose start` is suitable only when unchanged containers were stopped; it does not recreate containers after a configuration or image change. Docker reads the authentication mode from the root `.env` and builds the matching public browser mode from it: the default local capability demo works for one browser, while `hybrid` enables **Continue as guest** and account sign-up/sign-in when the JWT settings in [the guest and JWT guide](docs/PHASE_9_LOCAL_SETUP.md) are present.

Stop containers while retaining PostgreSQL and MinIO data with `docker compose --env-file .env --env-file infra/.env stop`. Use `down` only when you want to remove containers; do not add `--volumes` unless you intentionally want to erase local documents, metadata, vectors, and sessions.

### One-command Docker shortcuts

On Windows, use the included PowerShell helper. It runs the full build-and-start command by default:

```powershell
.\scripts\docker.ps1
```

Use `-Action start`, `stop`, `status`, `logs`, or `down` for the corresponding Compose operation. The `down` action intentionally preserves Docker volumes. A [Makefile](Makefile) provides the same `make up`, `make start`, `make stop`, `make status`, `make logs`, and `make down` targets for environments with GNU Make installed.

## Environment variables

Only `OPENAI_API_KEY` is required for the complete AI workflow. The local defaults are suitable for the assessment demo.

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes for OCR/extraction/Q&A | Server-only key for OpenAI document processing. |
| `NEXT_PUBLIC_API_BASE_URL` | No | Browser API address; defaults to `http://127.0.0.1:8000`. |
| `NEXT_PUBLIC_AUTH_MODE` | No | `capability` for the ready-to-run local demo; `hybrid` for guest plus demo sign-in; `jwt` for a signed-in workspace. It must match the backend mode. |
| `NEXT_PUBLIC_SELF_REGISTRATION_ENABLED` | No | Controls whether the browser offers the local sign-up route. It must match the backend setting and defaults to `false`. |
| `LICENCEIQ_AUTH_MODE` | No | Backend switch for guest capability, JWT, or hybrid access. |
| `LICENCEIQ_SELF_REGISTRATION_ENABLED` | No | Enables local account creation only for the development durable PostgreSQL profile. It defaults to `false` and is rejected in production. |
| `LICENCEIQ_DOCUMENT_STORAGE_BACKEND` | No | Selects private filesystem or MinIO storage for original bytes. |
| `LICENCEIQ_DOCUMENT_METADATA_BACKEND` and `LICENCEIQ_DATABASE_URL` | No | Select `postgres` to keep metadata, evidence, vectors, principals, and sessions in PostgreSQL. This mode requires MinIO byte storage and a PostgreSQL `psycopg` URL. |
| `LICENCEIQ_QUESTION_GUARDRAILS_ENABLED` | No | Enables local NeMo input/output policy checks for Q&A. It is `true` by default; set it to `false` only for local troubleshooting. |
| `LANGFUSE_TRACING_ENABLED` | No | Enables optional Langfuse operation telemetry only when a public key, secret key, and base URL are also present. It defaults to `false`. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` | No | Server-only Langfuse project credentials and Cloud/self-hosted root URL. Never commit keys. |
| `LANGFUSE_CAPTURE_IO` | No | Privacy invariant fixed to `false`; LicenceIQ never exports prompts, responses, document content, user data, identifiers, credentials, or raw errors. |

All optional limits, model settings, JWT settings, and MinIO settings are documented in [`.env.example`](.env.example). See the [private JWT/MinIO setup guide](docs/PHASE_9_LOCAL_SETUP.md) before enabling those optional modes. Never put secrets in `NEXT_PUBLIC_*` variables.

See the [Langfuse setup and privacy contract](docs/LANGFUSE.md) before enabling telemetry. The repository includes offline coverage for the tracing boundary, but no live trace audit is claimed without user-supplied project credentials.

The [Phase 10B durable runtime](docs/PHASE_10B_DURABLE_RUNTIME.md) adds the local MinIO/PostgreSQL profile. It is opt-in: the copied environment file remains the zero-infrastructure demo, while the durable profile requires Docker and its database migration.

## Access modes

| Mode | Use case | Credential boundary |
| --- | --- | --- |
| `capability` | Default local assessment demo | Upload returns one high-entropy document capability, retained only in browser memory. |
| `hybrid` | Interview demonstration of both paths | Guests use `X-Document-Capability`; signed-in users use a short-lived JWT. The two credential types cannot access each other’s documents. |
| `jwt` | Authenticated local/production foundation | A configured bootstrap account receives a short-lived JWT; the local durable profile can also opt into development-only accounts. Each document is bound to its token subject. |

`hybrid` is deliberately blocked in production because a public guest service also needs rate limits, malware scanning, monitoring, and other operational controls. Local self-registration also remains unavailable in production; it is an interview/demo feature, not public account management.

## AI and RAG approach

```text
Document -> parsing/OCR -> page text and evidence blocks
         -> strict structured extraction -> local evidence validation
         -> reviewer correction layer
         -> direct lookup or hybrid retrieval -> grounded cited answer
```

1. Each PDF page first attempts native text extraction. Image licences and unreadable PDF pages are prepared as bounded images for vision OCR.
2. Structured extraction returns values plus stable evidence block IDs. The backend resolves each ID against its own stored reading and rejects unsupported values.
3. Reviewer changes are saved beside, never inside, the original extraction.
4. Known questions such as “What is the licence number?” use the validated extracted field directly and avoid an unnecessary LLM call.
5. Broader questions use a bounded, private semantic-plus-lexical search over blocks from the active document only. A grounded answer must cite selected evidence; otherwise the application returns an unavailable response.
6. Every provider answer is checked against the cited source terms before it can be returned. Optional NeMo input/output rails reject prompt-control attempts and prompt leakage; they receive only the question or final answer, not licence text or retrieved evidence.

## Key technical decisions

- **Separate OCR from extraction.** OCR produces reusable page text; extraction converts that text into a structured licence record. This makes failures and evidence easier to inspect.
- **Keep providers behind adapters.** The application can replace the OCR, extraction, answer, or embeddings provider without changing API routes or review rules.
- **Use strict structured output.** Extraction targets a defined licence schema before local evidence validation, which keeps the review form predictable even when a field is unavailable.
- **Validate model output locally.** A JSON-shaped model response is not enough: each returned field and answer citation must resolve to stored evidence.
- **Use policy rails as a separate boundary.** Optional NeMo Guardrails run locally around document Q&A, while deterministic evidence checks remain responsible for whether an answer is supported by the document.
- **Preserve provenance.** A reviewer correction does not overwrite the source extraction or become evidence for later document Q&A.
- **Bypass the LLM for known fields.** Direct answers are faster, less expensive, and deterministic when a validated extracted field already answers the question.
- **Separate guest and signed-in credentials.** A guest capability is scoped to one temporary document; a JWT is scoped to one user subject. Hybrid mode rejects ambiguous requests and never lets an invalid JWT fall back to guest access.
- **Use a modular monolith.** It is the right level of architecture for a 48-hour assessment and avoids unnecessary infrastructure.

## Validation

Latest local verification completed successfully:

- The full offline backend suite passed, including hybrid guest/JWT isolation, durable-session checks, and durable-schema migration checks.
- Ruff, formatting, strict mypy, and dependency-lock checks passed.
- ESLint, TypeScript, Prettier, and production frontend builds passed in capability, hybrid, and JWT modes.
- Live OCR, extraction, review/save, direct Q&A, paraphrased retrieval, and safe abstention were exercised using the supplied fictional samples.

Run the checks yourself:

```powershell
cd backend
uv run pytest
uv run ruff check app tests --no-cache
uv run mypy app
```

```powershell
cd frontend
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run format:check
npm.cmd run build
```

Detailed evidence is available in the [phase reports](docs/), without adding their phase-by-phase history to this reviewer README.

## Known limitations

- OCR accuracy varies with scan quality, small text, tables, and languages. Visual human review remains necessary.
- Licence authenticity, portrait/signature identity, QR validation, and legal permission inference are out of scope.
- Live verification covers the supplied fictional samples; it is not a broad accuracy benchmark.
- Evidence navigation uses page and excerpt references. It cannot promise pixel-perfect OCR highlighting because the OCR provider supplies no reliable coordinates.
- The local demo uses temporary private storage. Guest document capabilities and JWTs remain only in browser memory. Optional local accounts have no email verification, password reset, rate limits, audit trail, or public-production support.
- The durable MinIO/PostgreSQL profile was exercised against the local containers with a provider-free test document. It is not a public deployment or a backup/recovery validation.
- The optional NeMo policy rails use deterministic local rules for prompt-control and prompt-leakage patterns. They complement source grounding; they are not a replacement for broader content moderation or adversarial evaluation.
- There is no public deployment. Local setup is provided, as allowed by the assessment brief.

## Production improvements

Before public deployment, replace the bootstrap/local-account flow with an OIDC identity provider such as Keycloak, use Auth.js in Next.js for its secure session layer, and validate provider JWTs through JWKS in FastAPI. Also add email verification and recovery, public abuse controls, malware scanning, per-user rate limits, encrypted backups, audit logging, monitoring, and cross-worker processing coordination. A queue and isolated parsing workers would be appropriate only after real workload demands them.

## AI-assisted development

OpenAI Codex was used for requirements analysis, implementation, review, and validation. The coding-orchestrator workflow selected an appropriate model route for bounded work based on complexity and risk. No other AI development tool is claimed.

## Demo and submission

The 5:18 captioned demo video is supplied separately from the repository; Git intentionally excludes binary recordings and local runtime artifacts. The [demo script](docs/DEMO_SCRIPT.md) and [submission checklist](docs/SUBMISSION_CHECKLIST.md) cover the requested 5–10 minute walkthrough and final delivery steps.
