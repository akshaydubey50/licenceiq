# Phase 10B: durable runtime

Status: complete on 20 September 2026 for the local Docker profile.

## Result

The durable profile is now selectable by configuration. MinIO stores only original PDF/image bytes. PostgreSQL with pgvector is the source of truth for the document record, access principal, lifecycle, reading pages, source evidence, embedding vectors, and JWT session state.

```text
Browser -> FastAPI -> MinIO      generated content object only
                  -> PostgreSQL  metadata, evidence, embeddings, principals, sessions
```

New uploads in this profile create only `documents/content/<generated-uuid>.bin` in MinIO. The application does not write or read a MinIO metadata object. Any older `documents/metadata/` objects belong to the former MinIO-sidecar profile; leave them until no legacy document needs them, then remove them through a deliberate cleanup operation.

## Enable the local profile

1. Start the loopback-only services using the instructions in [the infrastructure guide](../infra/README.md).
2. Build `LICENCEIQ_DATABASE_URL` from the ignored values in `infra/.env` and apply `uv run alembic -c alembic.ini upgrade head` from `backend/`.
3. In the ignored root `.env`, set:

   ```dotenv
   LICENCEIQ_DOCUMENT_STORAGE_BACKEND=minio
   LICENCEIQ_DOCUMENT_METADATA_BACKEND=postgres
   LICENCEIQ_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>
   ```

The API rejects a partial durable configuration. PostgreSQL metadata requires MinIO bytes, a database URL, and the fixed `256` embedding dimension used by `pgvector`.

## Persistence behavior

- A guest document persists its one-way capability hash in PostgreSQL. An authenticated document resolves an `app_users` principal by JWT issuer and subject, then stores the matching `owner_user_id`.
- Saving the first reading writes a `readings` row, page rows, and stable evidence blocks in the same transaction that updates the current document snapshot.
- Saving a semantic index validates its reading digest and source block IDs, then writes one `embedding_sets` row and one `block_embeddings.embedding vector(256)` value for every selected block. A failed normalized write rolls back the snapshot update too.
- Issuing a JWT in the durable profile creates an `auth_sessions` row with its opaque session ID and JWT ID. Every authenticated request checks the signed token and the active session; `POST /api/auth/logout` revokes only the caller's session.
- When explicitly enabled in development, local sign-up stores one Argon2 hash and normalized username in `local_credentials`, linked to an opaque `app_users` subject. It is disabled by default and unavailable in production.
- Expiry and delete move the document through a retryable database lifecycle before deleting its MinIO blob. Deleting the document cascades its relational evidence and vectors.

The current question service keeps its existing bounded, deterministic per-document ranking over the persisted snapshot, so assessment behavior stays stable. The same vectors are now retained in pgvector; a future retrieval phase can move ranking into PostgreSQL without reprocessing documents. Extraction and review snapshots are already durable in `documents.record_json`; writing separate normalized extraction/review history rows is a later enhancement.

## Verification

- Full offline backend suite, Ruff, and strict mypy passed.
- Alembic migrations through `20260920_0003` were applied to the local PostgreSQL container, including the opt-in local-account credential table.
- A live provider-free smoke check uploaded a PNG, read it, restarted the application, saved 256-dimensional vectors, verified PostgreSQL rows and the sole MinIO content blob, created and revoked a session, then deleted the test document and verified cascading cleanup. A final probe through the listening API verified that its upload path uses the same durable profile.

No real licence or OpenAI request was used for this infrastructure verification.
