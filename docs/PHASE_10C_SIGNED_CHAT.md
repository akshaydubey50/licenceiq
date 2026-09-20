# Phase 10C: signed-user resumable document chat

## Outcome

Authenticated JWT users can resume validated question history for documents they own when the
durable PostgreSQL profile is active. Guest and capability-only access remains ephemeral.

The public contract is:

- `GET /api/documents` returns at most 50 newest active documents owned by the JWT subject.
- `GET /api/documents/{id}/chat-history` returns up to 100 current-reading turns in chronological
  order.
- `DELETE /api/documents/{id}/chat-history` removes the owned document's saved turns.
- `POST /api/documents/{id}/questions` saves its validated result automatically after grounding,
  citation validation, output guardrails, and the existing source-freshness check.

Cross-owner and missing-document access share the existing generic document-not-found response.
The list and history endpoints require a JWT even in hybrid mode and never expose guest documents.

## Persistence and lifecycle

Migration `20260920_0004` adds `chat_turns`. Each row contains only the public `QuestionResult`
fields and the immutable SHA-256 digest of the reading used to answer it. It does not contain model
prompts, provider request or response payloads, embeddings, tokens, JWTs, or capabilities.

The reading foreign key cascades from document deletion, including expiry cleanup. An explicit
successful read request clears saved turns before returning, preventing old citations from being
shown after source evidence is refreshed. PostgreSQL failures do not make document questions fail;
history endpoints return the controlled `CHAT_HISTORY_UNAVAILABLE` response instead. No filesystem
or object-store metadata fallback is used for chat.

## Routing and verification

This high-impact privacy and ownership work scored 7/8 and used the required strong route:
`gpt-5.6-sol` with high reasoning, attempt 1 of 3, without escalation or nested delegation.

Offline verification covered JWT and guest boundaries, cross-owner isolation, bounded document
listing, validated answer and citation round trips, guardrail failures, persistence outages,
re-read invalidation, and deletion/expiry cascade declarations. Focused Ruff formatting/lint,
Mypy, and Pytest checks passed. Live PostgreSQL, MinIO, and OpenAI were intentionally not started.
