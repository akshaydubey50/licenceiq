# Phase 6: source navigation and evidence highlighting

Status: complete on 19 September 2026. This phase lets a reviewer follow an extracted-field source or a cited answer back to the active document's page and exact stored evidence excerpt. The detailed behavioral boundary is [the Phase 6 contract](PHASE_6_CONTRACT.md).

## What changed

The browser maintains a document-scoped selected-source state only in memory. A field source is selectable only when its immutable evidence resolves to the active reading; an answer citation is selectable only when its already validated `(page_number, block_id)` resolves to the same reading. Source references are now accessible buttons labelled with their page numbers.

Selecting a source focuses and scrolls the preview region, gives the preview an accessible selected-page description, and renders the exact source text as React text in a labelled **Source evidence** panel. The panel includes the page number and a clear-focus control. It resets on reread, replacement, removal, server-side removal, and component unmount.

For a PDF, the preview and open-preview link receive a best-effort `#page=<n>` fragment. Images show the selected-source state without invented coordinates. OCR evidence normally contains no reliable bounding box, so this phase deliberately does not draw pixel-accurate rectangles over licences.

No backend route, provider call, storage mechanism, authentication behavior, document lifecycle contract, or public API response changed.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) scored the frontend work at 7/8 and selected the strong tier. The coordinator fixed the provenance contract, prepared browser acceptance, reviewed the worker result, and verified the integrated behavior.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Source controls, selected evidence state, preview behavior, and responsive styles | [7/8, medium risk](routing/phase-6-frontend-assessment.json) | `/root/phase6_frontend`, `gpt-5.6-sol` / `high` | 1 / 0 | Accepted |
| Contract, routing, browser acceptance, code review, build, and reporting | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

## Verification

| Check | Observed result |
| --- | --- |
| Frontend route type generation and TypeScript | Passed |
| ESLint | Passed with zero warnings |
| Prettier check | Passed |
| Production frontend build | Webpack build completed: compilation, TypeScript, static generation, and route output passed |
| Offline browser acceptance | 8 passed: field excerpt, clear focus, cited-answer excerpt, unavailable-answer absence, removal reset, PDF fragment, mobile width, and no runtime errors |
| Visual review | Mobile source-evidence layout inspected on the fictional Delhi sample fixture; no horizontal overflow observed |

The browser test uses synthetic source evidence and mocked read/extract/fields/question responses after the frontend starts. It verifies UI provenance and lifecycle behavior without an OpenAI call, paid API usage, or retained test document. The PDF check verifies the iframe page fragment handoff; it does not claim every browser's native PDF viewer will honor the fragment.

## Remaining limits

- Source evidence is page- and block-aware, but usually not coordinate-aware. The app cannot truthfully draw precise text highlights over scanned licences without reliable OCR geometry.
- Native PDF viewers can ignore `#page=<n>` fragments. The rendered evidence panel is the reliable proof surface.
- This remains a one-document local demo with temporary private filesystem storage and capability access, not MinIO storage or JWT user accounts.
- No provider, backend, or broad-document accuracy test was added in this frontend-only phase.
