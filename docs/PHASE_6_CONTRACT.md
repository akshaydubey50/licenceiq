# Phase 6: source navigation and evidence highlighting contract

## Authorized scope

Make the source pages already shown by the Phase 3 review form and Phase 5 answers useful to a reviewer. A reviewer can activate a source reference to focus the preview on its source page and read the exact stored evidence excerpt in the workspace.

This is a frontend-only phase. It does not add accounts, JWT, MinIO, a database, embeddings, OCR/extraction/Q&A provider calls, new backend routes, or document reprocessing.

## Evidence and provenance boundary

- Navigation may use only page numbers and block IDs already present in the active document reading, an extracted field's immutable evidence, or a validated Phase 5 answer citation.
- Reviewer edits remain separate from source evidence. They must not create a source reference, change an excerpt, or influence a source focus.
- The selected source state stays in browser memory and is cleared when a document is replaced, removed, or the workspace unmounts.
- The UI must not invent a bounding box or imply pixel-exact highlighting when OCR geometry is absent. It shows a clearly labelled evidence excerpt instead.

## Interface behavior

- Existing page references beside source-derived fields and cited answers become keyboard-accessible controls with descriptive labels.
- Activating a reference selects the matching page, focuses the document preview region, and displays a labelled source-evidence panel with the page and exact stored excerpt when one is available.
- For image documents, page one remains the preview and gains an accessible focused-source state. For PDFs, the preview receives a best-effort `#page=<n>` fragment. Native browser PDF viewers may ignore that fragment; the evidence panel remains the reliable verification surface.
- A reviewer can clear the focused source and return to the ordinary preview. The interaction must remain usable on narrow screens without horizontal scrolling.

## Safety and verification boundary

- The frontend must continue strict response validation. A question citation can be navigable only if its `(page_number, block_id)` pair resolves in the active reading.
- Source excerpts render as React text, never HTML.
- Offline browser coverage must verify a field source and a chat citation navigate to the correct page/excerpt, unknown or unavailable answers cannot create a source control, cleanup clears the selected source, and the layout remains accessible and narrow-screen safe.
- Run frontend formatting, lint, type checks, and a production build after integration. Do not make live provider calls for ordinary verification.
