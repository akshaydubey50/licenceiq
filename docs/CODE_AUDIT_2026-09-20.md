# Code audit — 20 September 2026

This review covered maintained backend, frontend, persistence, migration, configuration, and infrastructure files. Generated dependencies, sample images, runtime data, and historical phase reports were excluded. Document contents were treated as untrusted evidence throughout the review.

## Corrected findings

| Priority | Finding | Correction |
| --- | --- | --- |
| P1 | Production accepted `minio_secure=false`, allowing private document traffic over plaintext transport. | Production settings now require secure MinIO transport. |
| P1 | Filesystem conditional writes did not include `owner_subject` in their snapshot comparison. Delayed reading, extraction, index, or review work could publish after ownership changed. | All filesystem conditional writes now check the complete access principal. |
| P1 | A new reading could appear beside an old extraction, form, source selection, or chat transcript when later pipeline work failed. | The frontend publishes a reread atomically after reading, extraction, and fields all succeed, then clears old Q&A state. |
| P1 | Replacing, removing, signing out of, or leaving a guest workspace could discard unsaved review edits. A guest could also lose the only document capability without warning. | The UI warns for unsaved edits, warns before every guest exit, and explains retention and capability loss. Browser tab close also receives the standard unsaved-change prompt. |
| P1 | The upload interface only disclosed OpenAI use for scanned-page reading. | The disclosure now covers scanned-page reading, structured extraction, and document Q&A. |
| P2 | A failed MinIO deletion during expiry cleanup prevented cleanup from continuing and could block later authorised requests. | Cleanup now skips the failed expired document and continues with unrelated records. |
| P2 | An expired document could remain as a misleading browser preview after read, save, question, or remove calls returned 404. | The UI revokes the preview, clears review and Q&A state, and gives a retention-aware notice. |
| P2 | Browser responses had no baseline defensive headers. | The frontend adds `nosniff`, same-origin frame protection, no-referrer policy, and restrictive device-permission headers. |

During integrated validation, newly added durable-session work also exposed a missing API response import, an invalid Python expression, a stale migration-head assertion, and formatter violations. Those integration errors were corrected without changing the durable-session design.

## Confirmed strengths

- Uploads use bounded request and file limits, magic-byte/type checks, strict PDF and image decoding, random private keys, and private storage.
- Guest capabilities and JWT identities remain separate; documents are checked against the active credential on every access.
- OCR, extraction, retrieval, and answers remain evidence-scoped to the active document. NeMo rails receive only the question or final answer.
- Client credentials remain in memory, and browser object URLs are revoked during cleanup.
- API error responses hide private provider, parsing, and storage details.

## Remaining limits before public production

- The frontend has static checks but no behavioural or browser-level regression suite. Add tests for dirty-state transitions, expiry, aborts, guest/JWT headers, and the complete upload-to-Q&A path.
- The object-store repository uses process-local locking. A multi-worker deployment needs a durable compare-and-swap or transactional metadata layer.
- The optional durable profile needs continued live integration coverage for PostgreSQL, MinIO, session revocation, object cleanup, and migration upgrade/rollback paths.
- Public deployment still needs rate limiting, malware scanning, monitoring, audit logs, an identity provider, and a document inventory/reopen flow.
- MinIO’s container image should be pinned by digest before a reproducible deployment; the local assessment compose file currently uses an unpinned image reference.
- A Content Security Policy and production HSTS were not added because the current local and `blob:` document preview behaviour needs a deliberate browser compatibility test first.

## Validation performed

- Full offline backend test suite passed after the integrated fixes.
- Ruff lint and format checks passed.
- Strict mypy passed for 41 backend source files.
- Frontend TypeScript checking, ESLint, Prettier, and the Next.js production build passed.
- No live OpenAI provider call or public deployment was performed as part of this audit.
