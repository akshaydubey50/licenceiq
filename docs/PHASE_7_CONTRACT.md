# Phase 7: semantic retrieval with temporary embeddings contract

## Authorized scope

Improve broader document questions with semantic retrieval while retaining the Phase 5 answer API, source citations, explicit abstention, and Phase 6 source navigation. This phase adds a server-side, temporary embedding index for the active document's immutable reading blocks.

It does not add MinIO, JWT/user accounts, a database, an external vector database, web search, long-term chat history, document reprocessing, or changes to the browser API response shape.

## Data and provider boundary

- Direct field questions continue to use immutable evidence-backed extraction and must never invoke an embedding or answer provider.
- A semantic index contains only active-document reading-block IDs and numeric vectors. It does not contain files, previews, capabilities, reviewer values, browser transcript entries, question answers, or data from other documents.
- The OpenAI embedding adapter receives only bounded active-document reading-block text or one question. It uses the configured server-only key, no automatic SDK retries, a bounded timeout, and `text-embedding-3-small` by default with a configured reduced dimension.
- A model result can select evidence for the answer provider only after local validation that the vector count, dimensions, finiteness, and block-ID ordering match the submitted blocks. The answer provider receives reading text and IDs only; never vectors.
- The index is private temporary document state, is cleared by existing deletion/expiry lifecycle, and is invalidated when its reading, model, or configured dimension does not match.

## Retrieval and answer behavior

- For a non-direct question, build or retrieve the document's semantic index, embed the question, calculate cosine similarity locally, and combine semantic and existing lexical scores deterministically.
- Continue to enforce the existing selected-block and selected-character limits before asking the answer provider.
- The answer provider must still cite selected original block IDs. Existing current-document, duplicate, unknown, cross-document, malformed, delete/expiry, timeout, and unavailable-answer protections remain mandatory.
- A semantic index failure returns an existing controlled question error and never exposes embedding/provider details or publishes a partial index.
- The question API response remains `QuestionResult`; it does not expose scores, vectors, model names, or retrieval implementation details.

## Configuration and verification

- Add explicit bounded embedding model, dimension, timeout, index-block, and index-character settings. Document defaults in `.env.example` and the README.
- Offline tests use a fake embedding provider and cover semantic-only retrieval, hybrid deterministic ordering, cache reuse/reload/invalidation, malformed provider vectors, direct-question provider avoidance, protected access, deletion/expiry races, and unchanged citation validation.
- Adapter tests mock the OpenAI SDK transport and verify the configured model/dimensions, bounded input/timeout, ordering, missing-key behavior, malformed responses, and no retries.
- Run the full backend suite, Ruff, format, strict mypy, and dependency-lock verification. A live OpenAI exercise is separate from offline acceptance and must use only the supplied fictional samples.
