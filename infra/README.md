# Local durable infrastructure

This directory supplies local PostgreSQL/pgvector and MinIO credentials for LicenceIQ's durable profile. The root Compose stack can now also run the frontend and API; none of these services are public.

## Prepare local-only secrets

Copy the template to the ignored file and replace every placeholder. Generate values without placing them in source control:

```powershell
Copy-Item infra/.env.example infra/.env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use a different generated value for each password or root credential. Never reuse the MinIO root credential as the application credential. Add a separate `LICENCEIQ_MINIO_APP_SECRET_KEY`; Compose provisions that application account with access only to LicenceIQ's private bucket.

## Start only the infrastructure

With Docker Desktop running, start only the infrastructure:

```powershell
docker compose --env-file .env --env-file infra/.env up -d --wait postgres minio minio-bootstrap
docker compose --env-file .env --env-file infra/.env ps
```

PostgreSQL is reachable only at `127.0.0.1:5432`; MinIO's S3 API and console are reachable only at `127.0.0.1:9000` and `127.0.0.1:9001`. Stop the stack while preserving volumes with:

```powershell
docker compose --env-file .env --env-file infra/.env stop postgres minio minio-bootstrap
```

Do not use `down --volumes` unless you intentionally want to destroy local database and object data.

## Run the full application stack

Use the root Compose file with both ignored environment files. The root `.env` supplies the application configuration and OpenAI key; this `infra/.env` supplies the database and MinIO credentials.

```powershell
docker compose --env-file .env --env-file infra/.env up -d --build --wait
docker compose --env-file .env --env-file infra/.env ps
```

The backend waits for PostgreSQL and MinIO bootstrap, applies Alembic migrations, then performs the document-free OpenAI preflight. A failure leaves the API stopped instead of accepting uploads that cannot be processed.

## Apply the database schema

After PostgreSQL is healthy, run the versioned schema migration from the backend directory. The generated `token_urlsafe` password recommended above contains only URL-safe characters.

```powershell
$env:LICENCEIQ_DATABASE_URL = "postgresql+psycopg://licenceiq:<LICENCEIQ_POSTGRES_PASSWORD>@127.0.0.1:5432/licenceiq"
cd backend
uv run alembic -c alembic.ini upgrade head
```

Replace the placeholder with the value from the ignored `infra/.env` file. This creates the `vector` extension and the private metadata, evidence, embedding, and session tables.

## Select the durable application profile

Add the following to the ignored root `.env`, using the same local PostgreSQL URL used for the migration:

```dotenv
LICENCEIQ_DOCUMENT_STORAGE_BACKEND=minio
LICENCEIQ_DOCUMENT_METADATA_BACKEND=postgres
LICENCEIQ_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>
```

Start the API after the migration. In this profile MinIO stores only original file bytes, while PostgreSQL owns metadata, evidence, embeddings, principals, and sessions. Details and verification evidence are in [Phase 10B](../docs/PHASE_10B_DURABLE_RUNTIME.md).

## What this enables

- PostgreSQL includes the `pgvector` extension required by the durable metadata and embedding store.
- MinIO provides a private local S3-compatible endpoint for original document bytes only.
- The filesystem/capability demo remains the default until the durable environment variables above are set.

The MinIO root account configures the local service. A future durable runtime must use a bucket-scoped service account with only the actions needed for LicenceIQ's private bucket.
