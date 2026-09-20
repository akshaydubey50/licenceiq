# Phase 10A: durable platform foundation

> Historical foundation note: this document records the initial schema and local-compose setup. Its deferred runtime work is implemented in [Phase 10B](PHASE_10B_DURABLE_RUNTIME.md).

## Goal

Prepare local, private infrastructure for a later durable LicenceIQ profile without weakening the existing assessment demo. Original document bytes belong in MinIO. PostgreSQL, with pgvector, will become the source of truth for ownership, lifecycle, review records, retrieval evidence, embeddings, and revocable sessions.

## Storage boundary

```text
Browser -> FastAPI -> MinIO: original PDF/image bytes under generated keys
                    -> PostgreSQL: ownership, lifecycle, pages, evidence,
                       extraction, review, embeddings, and session state
```

No filename, bearer token, guest capability, OCR text, or embedding is allowed in a MinIO object key. The legacy filesystem repository remains the default demo profile. Phase 10A does not dual-write temporary documents between the legacy and durable stores.

## Local services

[`compose.yaml`](../compose.yaml) starts a loopback-only PostgreSQL/pgvector container and a loopback-only MinIO container. The ignored credentials file is [the infrastructure template](../infra/.env.example); [the infrastructure guide](../infra/README.md) describes the local commands.

At the time of the foundation change, the stack had not been started. The later Phase 10B runtime was migrated and smoke-tested against the local PostgreSQL/pgvector and MinIO containers.

## Durable profile sequence

1. Run the versioned PostgreSQL migration and validate the pgvector extension.
2. Add a metadata repository that writes lifecycle rows before/after MinIO operations using explicit pending and active states.
3. Move page/evidence persistence, extraction/review payloads, then embedding rows behind the existing service-facing repository contract.
4. Add a session store that validates an active session ID after JWT signature validation and supports logout/revocation.
5. Add reconciliation and indexed expiry cleanup before enabling multiple API workers.

The application now selects the durable profile only when both the MinIO byte store and PostgreSQL metadata settings are complete. See [Phase 10B](PHASE_10B_DURABLE_RUNTIME.md) for the active contract and remaining retrieval work.

## Retrieval decision

Evidence blocks retain their stable IDs and source order. PostgreSQL holds one embedding set per reading hash, model, and dimension plus a `vector(256)` for every block. Retrieval must filter by the authorized active document before both lexical and semantic ranking, fuse the two bounded result sets deterministically, and retain the existing evidence-backed direct-field shortcut.

At the current 256-block per-document limit, an exact cosine scan after the document filter is sufficient. HNSW tuning is deferred until measured corpus size justifies it.

## Session decision

At this foundation milestone, the bootstrap JWT was short-lived and browser-memory-only. The durable schema reserved a session ID and JWT ID for active-session lookup, logout, expiry, and revocation. A later local-development update added opt-in PostgreSQL-backed registration; it still does not introduce refresh tokens, password recovery, cookies, or account profiles. A real production identity migration remains Keycloak OIDC plus Auth.js and JWKS validation.

## Acceptance boundary

Phase 10A is complete only when migrations are valid offline, the default demo remains unchanged, configuration contains no real secrets, and the guardrail contract is reviewable. A live stack requires Docker Desktop or an equivalent container runtime and must be reported separately from offline checks.
