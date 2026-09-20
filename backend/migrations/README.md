# LicenceIQ database migrations

This Alembic history defines the optional PostgreSQL durable-mode schema. It does not activate
database persistence in the application. Generate reviewable PostgreSQL SQL without connecting:

```powershell
uv run alembic upgrade head --sql
```

For a future online migration, set `LICENCEIQ_DATABASE_URL` to a
`postgresql+psycopg://...` URL. Keep credentials outside repository files. The database and MinIO
bucket must remain private; `documents.object_key` stores only an opaque generated key.
