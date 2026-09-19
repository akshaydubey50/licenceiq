# Phase 9: private deployment foundation

## Goal

Prepare LicenceIQ for an authenticated, self-hosted deployment without publishing the application. This phase replaces the local-demo assumptions that block a safe public URL: temporary local file storage and per-document browser capabilities.

## Confirmed decisions

- Document bytes and persisted metadata will support a self-hosted S3-compatible MinIO backend.
- JWT bearer tokens will identify the signed-in user.
- Each document belongs to one token subject. A token for one subject must never read, alter, answer questions about, or delete another subject's document.
- The existing filesystem repository remains an explicit development/test option so the verified local demo and offline tests continue to work.
- Secrets, MinIO credentials, and bootstrap login credentials stay server-side environment variables.
- No cloud account, external repository, deployment, or real licence document will be used in this phase.

## Boundary

Phase 9 provides the backend contracts, storage abstraction, authentication endpoint and frontend login/session flow, configuration examples, offline tests, and local deployment instructions. It does not create a public user-registration service, add MinIO/JWT credentials to source control, publish a URL, or upload any document outside the configured application provider calls.

## Authentication contract

- `development` retains an explicit local capability mode for the existing assessment demo.
- `jwt` mode requires a signed short-lived access token on document operations and binds new documents to its `sub` claim.
- JWT mode obtains a token only through a server-side configured bootstrap account. Self-registration and refresh tokens are outside this assessment scope.
- Production settings must reject capability mode, placeholder JWT keys, wildcard CORS origins, and missing configured storage settings.
- Authentication failures return a generic unauthorised response. Document ownership failures continue to look like a missing document so document IDs cannot be enumerated.

## Storage contract

- A repository interface owns document bytes and metadata persistence. The filesystem implementation remains the local default.
- The MinIO implementation stores private objects under generated keys only. Original filenames, document text, and bearer tokens must not appear in keys, logs, URLs, or error messages.
- Writes publish document bytes before their metadata. Failed writes remove any newly created object where possible.
- Read, update, delete, expiry cleanup, and ownership checks preserve the existing document lifecycle semantics.
- Local tests use fakes or mocks; no live MinIO service is required for ordinary verification.

## Acceptance checks

1. Existing local capability-mode tests remain green.
2. JWT tests cover valid login, malformed/expired/incorrectly signed tokens, missing authentication, document ownership isolation, and production configuration failures.
3. Storage tests cover generated key privacy, save/read/update/delete/expiry behavior, failed publish cleanup, and no token or filename leakage.
4. Backend static checks, lock validation, and frontend type/lint/build checks pass.
5. The README contains exact local MinIO and authenticated-run setup without containing a real secret.

## Remaining work after Phase 9

An external deployment may be prepared only after local acceptance. Its provider, domain, actual secrets, public privacy notice, rate limits, backups, and operational monitoring require a separate Phase 10 decision.
