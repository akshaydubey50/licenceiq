# Phase 7: semantic retrieval with temporary embeddings

Status: complete on 19 September 2026. This phase improves broader document questions when the question and source text use different wording, while preserving the existing question response, source citations, abstention behavior, document isolation, and Phase 6 source navigation. The behavioral boundary is defined in [the Phase 7 contract](PHASE_7_CONTRACT.md).

## What changed

Each active document can now hold a private `SemanticIndex` tied to its exact immutable reading, embedding model, dimensions, block order, and reading hash. The index contains only reading block IDs and validated numeric vectors. It is kept in the existing private document metadata, cleared when a reading is saved, and removed by the existing document deletion and expiry lifecycle. It is never returned by the API.

For a non-direct question, the backend builds or reuses this bounded index, embeds the one question, calculates cosine similarity locally, and combines that score with the existing lexical score using deterministic tie breakers. It sends only the selected original reading blocks to the existing answer provider. Direct structured-field questions remain on the evidence-backed lookup path and invoke neither the embeddings nor answer provider.

The OpenAI adapter uses `text-embedding-3-small` with configurable reduced dimensions, bounded input, a server-only key, and no automatic SDK retries. Provider outputs must have the expected count, dimensions, finite non-zero values, and original order before the index or retrieval can use them. Failures remain controlled question errors and do not expose provider details.

The added embeddings calls made the former 30-second overall question budget too short for a first semantic question in the live exercise. The default budget is now 60 seconds, while each embeddings request remains independently bounded at 15 seconds. The focused adapter and question tests cover that configuration change.

No browser API shape, frontend component, account model, storage provider, database, external vector database, MinIO integration, or JWT authentication was added.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) assessed the backend work at 8/8 with high risk because it crosses provider, storage, retrieval, evidence, and lifecycle boundaries. The strong route was selected. The coordinator defined the contract, reviewed the implementation, diagnosed the live timeout, applied the bounded configuration correction, and independently verified the result.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Embeddings contract, cache, provider adapter, hybrid retrieval, and offline tests | [8/8, high risk](routing/phase-7-backend-assessment.json) | `/root/phase7_backend`, `gpt-5.6-sol` / `high` | 1 / 0 | Accepted after review |
| Live-timeout diagnosis, default-budget correction, integration checks, and reporting | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

## Verification

| Check | Observed result |
| --- | --- |
| Full backend suite | 185 passed |
| Focused question, embeddings-adapter, and answer-adapter suite after timeout correction | 62 passed |
| Ruff check | Passed |
| Ruff format check | 41 files already formatted |
| Strict mypy for application source | Passed: 31 source files |
| Dependency lock | `uv lock --check` passed |
| Live embeddings connectivity | `text-embedding-3-small`, 256 dimensions, one bounded non-document test input passed |
| Live semantic acceptance | 5 passed cases: paraphrased expiry retrieval and cache follow-up for both fictional crops, followed by test-document deletion |

The live acceptance asks paraphrased expiry questions that do not use the direct-field trigger phrases. It verifies an answered response, validates all citations against the active reading, requires cited text to contain the independently extracted expiry value, and deletes each temporary document in a `finally` block. It does not print licence values, tokens, raw provider output, or document text.

## Remaining limits

- This is a small bounded local semantic cache, not an external vector database or cross-document search service.
- Only reading blocks within the configured block and character limits receive semantic vectors. Any later blocks can still be considered by the existing lexical path.
- A first broader question can take longer than a direct field question because it creates the temporary index. Indexes are rebuilt when the reading, model, dimensions, or indexed block order changes.
- Retrieval selects evidence; it does not make an answer trustworthy by itself. The separate answer provider must still cite selected source block IDs, and the backend validates those citations.
- The project remains a one-document local demo with private filesystem storage and a per-document capability. MinIO-compatible storage and JWT accounts are still deferred.
