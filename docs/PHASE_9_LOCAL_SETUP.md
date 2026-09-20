# Phase 9 local guest, MinIO, and JWT setup

This guide prepares a private local instance. It does not publish LicenceIQ or make its document bucket public.

## Keep the assessment demo unchanged

The existing fictional-sample walkthrough continues to use these defaults in the ignored root `.env` file:

```dotenv
LICENCEIQ_ENVIRONMENT=development
LICENCEIQ_AUTH_MODE=capability
LICENCEIQ_DOCUMENT_STORAGE_BACKEND=filesystem
```

The browser keeps the one-time document capability only in memory. This is suitable for the supplied localhost assessment demo, not for public hosting.

## Prepare private JWT settings

For an authenticated local instance, create a fresh, random signing key outside source control:

```powershell
cd backend
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Create an Argon2 password hash without placing the password in shell history:

```powershell
cd backend
uv run python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Bootstrap password: ')))"
```

Copy the generated values into the ignored root `.env`, together with a non-secret username and stable subject:

```dotenv
LICENCEIQ_AUTH_MODE=jwt
LICENCEIQ_JWT_SIGNING_KEY=<new-random-value>
LICENCEIQ_JWT_ISSUER=licenceiq-api
LICENCEIQ_JWT_AUDIENCE=licenceiq-browser
LICENCEIQ_JWT_ACCESS_TOKEN_TTL_SECONDS=900
LICENCEIQ_BOOTSTRAP_USERNAME=candidate
LICENCEIQ_BOOTSTRAP_PASSWORD_HASH=<argon2-value>
LICENCEIQ_BOOTSTRAP_SUBJECT=candidate-001
```

The application always retains one configured bootstrap account for local administration and demo access. It has no refresh-token service.

## Enable optional local account registration

Local sign-up is an opt-in development feature. It uses PostgreSQL to store an Argon2 password hash and opaque user subject, then creates the same short-lived, revocable JWT session as sign-in. It is disabled by default and rejected in production.

It requires the durable MinIO/PostgreSQL profile and a JWT signing key. A bootstrap account remains optional when local registration is enabled. In the ignored root `.env`, set:

```dotenv
LICENCEIQ_AUTH_MODE=hybrid
LICENCEIQ_JWT_SIGNING_KEY=<new-random-value>
LICENCEIQ_DOCUMENT_STORAGE_BACKEND=minio
LICENCEIQ_DOCUMENT_METADATA_BACKEND=postgres
LICENCEIQ_SELF_REGISTRATION_ENABLED=true
```

In `frontend/.env.local`, set the matching public flags:

```dotenv
NEXT_PUBLIC_AUTH_MODE=hybrid
NEXT_PUBLIC_SELF_REGISTRATION_ENABLED=true
```

Apply migrations from `backend/` before starting the API:

```powershell
uv run alembic -c alembic.ini upgrade head
```

The app then exposes `/login`, `/signup`, and `/logout`. Successful sign-in and sign-up redirect only to an internal LicenceIQ path. Username availability is never disclosed by the API. Usernames are normalized to lowercase `a-z`, digits, `.`, `_`, or `-` and must be 3–64 characters; passwords must be 7–256 characters.

## Run guest and signed-in flows together

For a local interview demonstration, set the backend `.env` and frontend `.env.local` to the matching hybrid values:

```dotenv
# Root .env
LICENCEIQ_AUTH_MODE=hybrid

# frontend/.env.local
NEXT_PUBLIC_AUTH_MODE=hybrid
```

Hybrid mode keeps the two security boundaries separate:

- A guest upload has no credentials. Its upload response contains a one-time document capability, and every later operation sends that value in `X-Document-Capability`.
- A signed-in upload sends its JWT in `Authorization: Bearer ...`. The resulting document belongs to the JWT subject and never returns a document capability.
- JWTs cannot open guest documents, and guest capabilities cannot open signed-in documents. Missing or mismatched credentials look like an unknown document. Invalid JWTs return `401`, and requests containing both credential types return `400`.
- In the durable PostgreSQL profile, **Sign out** calls `POST /api/auth/logout` before the browser clears its in-memory token. That revokes only the current database-backed session. If the server cannot confirm revocation, the browser keeps the session available so the user can retry.

The guest capability is returned only once and must be kept in browser memory. It does not appear in document metadata, storage keys, URLs, or logs.

## Prepare MinIO

Run MinIO on infrastructure you control, with a persistent local volume and non-public API/bucket. The application creates its configured bucket when its service credential has bucket-create permission. Give the application credential access only to its dedicated private bucket; do not reuse MinIO root credentials in LicenceIQ.

For a local container, use the current [official MinIO single-node deployment instructions](https://min.io/docs/minio/container/operations/install-deploy-manage/deploy-minio-single-node-single-drive.html). MinIO documents port `9000` for its S3 API and `9001` for the optional console. Keep the console private and choose credentials outside this repository.

Add the app credential and endpoint to the ignored root `.env`:

```dotenv
LICENCEIQ_DOCUMENT_STORAGE_BACKEND=minio
LICENCEIQ_MINIO_ENDPOINT=127.0.0.1:9000
LICENCEIQ_MINIO_ACCESS_KEY=<private-app-access-key>
LICENCEIQ_MINIO_SECRET_KEY=<private-app-secret-key>
LICENCEIQ_MINIO_BUCKET=licenceiq-private
LICENCEIQ_MINIO_PREFIX=documents
LICENCEIQ_MINIO_SECURE=false
```

Use `LICENCEIQ_MINIO_SECURE=true` with a TLS-protected endpoint for any non-local environment. The endpoint setting accepts only `host` or `host:port`; do not include `http://`, `https://`, a path, a bearer value, a filename, or a bucket policy URL.

## Start and verify

Set the frontend mode in `frontend/.env.local`. It must match the backend mode. Use `jwt` below for the signed-in-only flow, or replace both settings with `hybrid` for the two-choice demo above:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_AUTH_MODE=jwt
NEXT_PUBLIC_SELF_REGISTRATION_ENABLED=false
```

Then start the backend and frontend with the normal commands in the README. Sign in with the bootstrap account or, when local registration is enabled, create an account at `/signup` before uploading a document. A JWT belongs to one subject, and document operations for a different subject return the same missing-document response as an unknown ID.

For a production setting, LicenceIQ still requires JWT-only authentication and rejects both capability/hybrid guest modes and local self-registration. A public guest or account service needs rate limits, email verification/recovery, abuse controls, malware scanning, and operational monitoring that are outside this assessment. Production also rejects filesystem storage, non-HTTPS CORS origins, incomplete JWT settings, or incomplete MinIO credentials before the server starts. Run one backend worker: MinIO persistence does not yet provide cross-process compare-and-swap protection for concurrent lifecycle updates.
