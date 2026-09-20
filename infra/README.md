# Local durable infrastructure

This directory supplies the local MinIO and PostgreSQL/pgvector services planned for LicenceIQ's durable profile. It does not change the existing zero-infrastructure fictional-sample demo, and it does not make either service public.

## Prepare local-only secrets

Copy the template to the ignored file and replace every placeholder. Generate values without placing them in source control:

```powershell
Copy-Item infra/.env.example infra/.env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use a different generated value for each password or root credential. Never reuse the MinIO root credential as the application credential.

## Start and stop

With Docker Desktop running, start only the infrastructure:

```powershell
docker compose --env-file infra/.env up -d
docker compose ps
```

PostgreSQL is reachable only at `127.0.0.1:5432`; MinIO's S3 API and console are reachable only at `127.0.0.1:9000` and `127.0.0.1:9001`. Stop the stack while preserving volumes with:

```powershell
docker compose --env-file infra/.env down
```

Do not use `down --volumes` unless you intentionally want to destroy local database and object data.

## Apply the database schema

After PostgreSQL is healthy, run the versioned schema migration from the backend directory. The generated `token_urlsafe` password recommended above contains only URL-safe characters.

```powershell
$env:LICENCEIQ_DATABASE_URL = "postgresql+psycopg://licenceiq:<LICENCEIQ_POSTGRES_PASSWORD>@127.0.0.1:5432/licenceiq"
cd backend
uv run alembic -c alembic.ini upgrade head
```

Replace the placeholder with the value from the ignored `infra/.env` file. This creates the `vector` extension and the private metadata, evidence, embedding, and session tables. It does not switch the running application to the durable profile yet.

## What this enables

- PostgreSQL includes the `pgvector` extension required by the Phase 10 database migration.
- MinIO provides a private local S3-compatible endpoint for original document bytes.
- The Phase 10A schema and migration are deliberately separate from the running application. The existing filesystem/capability demo stays the default until the durable repository has been integrated and tested.

The MinIO root account configures the local service. A future durable runtime must use a bucket-scoped service account with only the actions needed for LicenceIQ's private bucket.
