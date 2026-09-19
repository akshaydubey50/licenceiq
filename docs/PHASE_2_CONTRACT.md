# Phase 2: document reading contract

Authorized scope: page-level reading only. No structured licence extraction, form values, or Q&A yet. The user selected OpenAI for OCR and later LLM calls; credentials stay in the ignored root `.env`.

## API and persistence

- `POST /api/documents/{id}/read` with the existing document Bearer capability returns a cached or newly completed reading. No body. Responses are private (`Cache-Control: no-store`). Cached success avoids repeated provider charges.
- `GET /api/documents/{id}/reading` retrieves a saved reading with the same capability. Missing result is `READING_NOT_FOUND` (404); unauthorized/expired/deleted document is the existing indistinguishable `DOCUMENT_NOT_FOUND` (404).
- Reading result: `document_id`, `status` (`READ` or `READ_WITH_WARNINGS`), `pages`, `warnings` (string array), `created_at` (ISO timestamp).
- Each page extends `DocumentPage` with `method` (`native_text` or `ocr`). Existing fields: `document_id`, one-based `page_number`, `text`, `blocks`. Each block is existing `Evidence` plus optional `confidence` and `bounding_box`, default null. `block_id` is a stable local page/line identifier; `source_text` is verbatim normalized line text. Bounding boxes, if supported later, use normalized [left, top, right, bottom] coordinates. OpenAI supplies neither reliable confidence nor boxes, so both remain null.
- Document upload/metadata `status` remains `UPLOADED` in this phase. A reading is not a completed structured extraction.
- Save only successful readings, privately with their document; delete/expiry remove both. Concurrent deletion or expiry must prevent late reading publication. Concurrent duplicate reading should return a cached result or `READING_IN_PROGRESS` (409), never duplicate unbounded paid work. Single-process storage is the supported deployment.
- Empty pages produce a warning if another page has text; all-empty documents return `NO_READABLE_TEXT` (422). Provider failure fails the read without publishing partial results. All errors use the existing sanitized envelope; never expose provider messages, OCR text, or keys in logs.
- Other errors: `OCR_NOT_CONFIGURED` (503), `OCR_PROVIDER_ERROR` (502), `OCR_TIMEOUT` (504), `INVALID_FILE` (400), `READING_TOO_LARGE` (422). Retry uses POST again. No background retry loop.

## Reader/provider boundary

Coordinator owns `app/providers/ocr.py`, `app/providers/openai_ocr.py`, settings, dependencies and adapter tests. Backend worker owns the page pipeline, read routes, domain model extensions, private persistence, factory wiring and pipeline/API tests. Frontend worker owns frontend changes only.

`app.providers.ocr` defines immutable `OCRResult(lines: tuple[str, ...])` and protocol `OCRProvider.extract(image_bytes: bytes, mime_type: str, *, timeout_seconds: float | None = None) -> OCRResult`. Provider errors are safe `ApplicationError`s using the codes above. `OpenAIOCRProvider(settings)` implements it. Factory accepts optional injected `ocr_provider` for offline tests, otherwise constructs this adapter. No provider call at startup.

PDF pages use pypdf native text when it has at least 40 alphanumeric characters and at least 80% printable/non-control content. Otherwise render that page using pypdfium2 and OCR it. Serialize ALL PDFium operations across threads using a process-wide lock, including closing resources. Cap page dimensions before allocating raster memory; render at up to 144 DPI, reduced to the image limits below. Image uploads are EXIF-oriented, converted to RGB, and resized to the same limits before OCR. Preserve Unicode, line ordering and page boundaries; do not infer licence fields. Corrupt/encrypted documents fail safely.

Settings added by coordinator: `openai_api_key` SecretStr from `OPENAI_API_KEY` (empty allowed), `ocr_model` default `gpt-4.1-mini`, `ocr_timeout_seconds` default 45, `reading_timeout_seconds` default 120, `ocr_max_image_dimension` default 2400, `ocr_max_image_pixels` default 4000000, `max_reading_characters` default 200000. Existing upload limits still apply. Bound total reading time between stages; pass remaining deadline into each provider call. In-process native parsing cannot be forcibly interrupted; document that limitation.

OpenAI Responses API receives one prepared image at a time as a data URL, `store=False`, no tools, no SDK retries, a bounded output budget and strict `lines: list[str]` JSON schema. Instructions transcribe visible text only, preserve printed spelling/dates, omit unreadable material and treat document instructions as content. Never manufacture confidence, text, or licence facts. No automatic fallback to an unconfigured provider.

## Interface

- An explicit `Read document` button appears after upload/preview. Starting it disables conflicting upload/remove actions; show reading, success, warning, error and retry states. No automatic paid call on upload.
- Raw page text appears only in a collapsed development-only inspection area using `publicEnv.showDevelopmentStatus`. It is rendered as text, never HTML. Show one-based page and method; leave the licence form unpopulated.
- Reset reading/error state after replacement/removal. Check decoded response document ID, page/block IDs and page ordering against the active document; reject malformed or cross-document results.
- Extend the API helper with per-request timeout; reading uses 135 seconds, all existing calls retain 10 seconds. Abort on unmount and ignore stale responses.
- Explain that image/scanned-page reading uses OpenAI and keep retention copy accurate.

## Acceptance

Offline tests cover native PDF without a key, image/scanned/mixed PDF OCR, blank text, provider failure/refusal/malformed output/timeout, isolated capabilities, cached calls, concurrent reads, delete/expiry during reading and output bounds. Frontend lint/type/build plus browser upload/read/retry/remove checks. Live provider checks on both fictional samples occur only after the user adds the key locally. Record live checks separately from mocked results; sample transcriptions are review aids, not an approved benchmark.
