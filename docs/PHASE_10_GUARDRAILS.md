# Phase 10 guardrail contract

These controls apply to the planned durable profile. They preserve the evidence and privacy boundaries already used by the assessment demo.

| Boundary | Required guardrails |
| --- | --- |
| Upload | Authenticate before expensive processing; stream-request and file-size limits; allowlisted MIME and magic bytes; strict PDF/image decode; page/pixel bounds; random private object keys; SHA-256; compensating cleanup. |
| Storage | MinIO bucket remains private; app uses a bucket-scoped service account; PostgreSQL owns metadata; credentials, document text, tokens, capabilities, and filenames never enter logs, URLs, or object keys. |
| OCR/extraction | Current document authorization, page/character/concurrency/timeout limits, strict schemas, no tools, document text treated as untrusted evidence, and local evidence validation before persistence. |
| Retrieval/Q&A | Same-document database filter before lexical or vector ranking; bounded selected blocks and characters; no web/tools; cited evidence must be current and selected; unsupported answers return the existing unavailable response. |
| Access | Argon2 credential checks, short JWT lifetime, issuer/audience/algorithm checks, active-session validation, logout revocation, generic authentication failures, and indistinguishable unknown/foreign documents. |
| Retention | Expiry denies access first; rows move to deletion-pending before deleting MinIO bytes; retried cleanup/reconciliation; indexed expiry query; dependent evidence, reviews, and embeddings removed only after the object lifecycle completes. |
| Operations | TLS outside localhost, no public MinIO console, readiness checks, privacy-safe structured logs, audit event types without document contents, database migrations, backup/restore drills, and rate limiting before public exposure. |

The following are deliberately outside the 48-hour assessment: public registration, refresh tokens, MFA, social login, cross-document search, chat history, autonomous agents, queues, approximate-index tuning, malware scanning service deployment, high availability, and public release.
