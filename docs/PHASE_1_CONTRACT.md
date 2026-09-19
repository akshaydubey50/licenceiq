# Phase 1 upload and preview contract

Authorized on 19 September 2026. Scope: real validated upload, private temporary storage, image/PDF preview, replacement, removal, errors, and verification. OCR and extraction begin in later phases.

## Shared API

- `POST /api/documents`: multipart field `file`; exactly one PDF, PNG, JPG/JPEG, maximum 10,485,760 bytes (displayed as 10 MB). Return HTTP 201 with the existing `Document` metadata flattened together with `access_token: string`. Keep the existing `size_bytes` field. Status is `UPLOADED`; image page count is 1, PDF page count comes from structural validation.
- `GET /api/documents/{document_id}`: return `Document` metadata.
- `GET /api/documents/{document_id}/file`: return original validated bytes with the detected MIME type, safe content disposition, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`.
- `DELETE /api/documents/{document_id}`: remove bytes and metadata, return 204.
- All operations on an existing document require `Authorization: Bearer <access_token>`. The server generates a high-entropy per-document capability at upload and stores only its hash. Do not put it in a URL or logs. Unknown documents and incorrect/missing capabilities return the same controlled 404 `DOCUMENT_NOT_FOUND` response. This local-demo capability is not user-account authentication.
- Preserve the existing `{error: {code, message}, request_id}` error envelope. Use `INVALID_FILE`, `UNSUPPORTED_FILE`, `FILE_TOO_LARGE`, `DOCUMENT_NOT_FOUND`, and controlled server errors as appropriate.

## Backend ownership and safeguards

Backend worker owns `backend/**`. Thin routes call a document service and private storage repository. Validate extension, declared MIME, magic/content, complete image decode or PDF structure, empty input, and byte limits. Reject encrypted/unreadable PDFs and excessive image dimensions/page counts with clear messages. Bound the multipart request before unbounded buffering, including requests without Content-Length. Keep actual storage keys generated and paths out of responses. Store metadata separately from public types. Temporary files expire after 24 hours, with cleanup on startup and document operations; document that no background scheduler runs while the API is stopped. Include focused offline tests for validation, private retrieval, deletion, and failure cleanup. No AI/provider calls.

## Frontend ownership and behavior

Frontend worker owns `frontend/**` except generated artifacts as normal tooling requires. Read `frontend/AGENTS.md` and installed Next.js guidance. Preserve the current visual style, keyboard support, and mobile layout. Centralize bounded requests and runtime response checks. Fetch preview bytes with the capability header and create/revoke local blob URLs; never use a token query parameter. Keep capabilities in memory only for Phase 1 and explain that refreshing begins a new workspace. Provide drag/drop, picker, selection details, loading/error/retry, replace, remove, and image/PDF previews. Do not populate extracted fields or imply OCR has happened.

Keep the current document when a replacement upload fails. After the replacement is ready, delete the old document; if cleanup fails, visibly explain the pending cleanup and allow retry (temporary retention remains the fallback). Removal must call the backend and report failure honestly. Disable conflicting actions while operations run and clean up preview URLs. A PDF browser preview may use the browser's viewer with a fallback open/download action; do not claim support for viewers that have not been checked.

## Coordinator ownership

The coordinator owns root files, `docs/**`, routing records, integration checks, and browser acceptance. Workers do not alter each other's files, global skills, sample originals, root documentation, or commit/push. Each has an initial implementation attempt with two corrections remaining and at most one model escalation across the entire work unit. No nested delegation.
