# Phase 9: private deployment foundation

Status: complete on 20 September 2026. Phase 9 adds a reviewable authenticated-storage foundation locally. It does not publish the application, connect to a live MinIO server, or move any real licence document outside the existing configured AI calls.

## What changed

- Added a JWT bootstrap login endpoint, short-lived access tokens, strict claim validation, and generic authentication failures. Tokens are signed with an allowlisted HMAC algorithm and require issuer, audience, subject, issued-at, not-before, expiry, and token-ID claims.
- Added a JWT browser gate that holds the bearer token only in React memory, sends it with each document request, expires it on time or any `401`, and supports explicit sign-out. Capability mode stays available for the recorded localhost assessment workflow.
- Added user ownership to private document records. In JWT mode, a different subject receives the same `DOCUMENT_NOT_FOUND` response as an unknown document ID.
- Added a MinIO/S3-compatible private object-store adapter and a MinIO document repository. It stores generated-key content and generated-key metadata beneath separate internal prefixes; neither filenames nor bearer values become object names or public URLs.
- Added strict production settings: production requires JWT, MinIO, complete server-only credentials, and HTTPS browser origins. Filesystem/capability mode remains an explicit local development/test choice.
- Added [local setup instructions](PHASE_9_LOCAL_SETUP.md), configuration examples, and package locks for `PyJWT`, `pwdlib[argon2]`, and the MinIO Python client.

## Verification

| Check | Observed result |
| --- | --- |
| Full backend suite | 223 tests collected and passed offline |
| Phase 9 focused checks | 38 passed: JWT claims/login, object-store behavior, ownership isolation, MinIO repository cleanup, and production-setting safeguards |
| Backend quality | Ruff, format, strict mypy, and lock check passed |
| Frontend quality | ESLint, type generation/TypeScript, and Prettier passed with Node 24 |
| Frontend production builds | Webpack builds passed with `NEXT_PUBLIC_AUTH_MODE=capability` and `jwt` |
| Live MinIO/deployment | Not run: no live infrastructure, credentials, or public release was used |

The workspace system Node 20.11 cannot resolve this project path in the sandbox and is below the frontend engine range. The frontend checks were run with the available Node 24 runtime. The npm launcher also resolves to the system Node, so the project-local Next, ESLint, TypeScript, and Prettier commands were invoked directly with Node 24.

## Remaining limits

- JWT mode uses one environment-configured bootstrap account. It is not self-registration, a user directory, multi-factor authentication, or refresh-token management.
- MinIO lifecycle updates have the existing process-local lock semantics. Run one backend worker until metadata updates use a durable cross-process compare-and-swap mechanism.
- A private TLS-enabled MinIO deployment, backup/recovery plan, rate limits, malware scanning, audit logging, monitoring, and a privacy notice remain prerequisites for an external deployment.
- The Phase 8 ZIP and demo video remain valid historical submission artifacts; regenerate the ZIP before sharing if the recipient needs these Phase 9 changes.

## Routing record

The coding-orchestrator assessments selected the strong route for all three security-sensitive work units: JWT foundation (8/8), MinIO object-store foundation (7/8), and browser token handling (6/8). The coordinator reviewed both worker outputs, wired their contracts together, and performed the combined checks. Details, real worker dispatches, attempts, and validation are recorded in [the Phase 9 routing record](routing/phase-9.json).
