# Phase 4: editable review form and durable save contract

Authorized scope: present one private Phase 3 extraction as an editable form, let the reviewer correct its values, and persist the reviewed layer with the same private document. This phase does not implement document Q&A, retrieval, user accounts, reprocessing, or a general data-export system.

## Review data and provenance

- Phase 3 `ExtractionResult` and every `ExtractedField` remain immutable source facts. Saving a correction must never alter an extracted value, raw value, warning, or evidence reference.
- A reviewed view contains the extraction plus `reviewed` values. Each primary value has `current_value` and server-derived `is_edited`; the original field is available separately for comparison and source pages.
- The first reviewed view derives `current_value` from the extraction and reports `is_edited=false`; it need not create a storage write. A save persists only the reviewer values and its timestamp.
- The review API accepts source-formatted text. It trims only leading/trailing whitespace, preserves internal punctuation/date order, permits `null` to intentionally clear a field, and derives edited state from the current value versus the corresponding original extraction value.
- The review layer includes the seven primary fields, an ordered list of vehicle-class values, and the extracted additional-information keys. The UI can edit values but cannot add arbitrary additional keys. Vehicle values are bounded, non-empty when present, unique after conservative normalization, and retain their input order.
- An absent extracted value may be supplied as a correction. A supported extraction’s evidence belongs only to that source extraction; a reviewer correction has no invented evidence.

## API and lifecycle

- `GET /api/documents/{document_id}/fields` returns a `FieldsResult`: `document_id`, immutable `extraction`, derived or stored `reviewed`, and `updated_at` when the reviewed layer has been saved. It requires the private Bearer capability and a saved extraction. A missing extraction returns `EXTRACTION_NOT_FOUND` (404); unknown, unauthorised, expired, and deleted documents remain `DOCUMENT_NOT_FOUND` (404).
- `PUT /api/documents/{document_id}/fields` accepts one complete `ReviewUpdate` under a `fields` object and returns the saved `FieldsResult`. It requires the same capability. Unknown JSON keys, unexpected additional-information keys, invalid/duplicate vehicle values, oversized values, and invalid document identity return a controlled `INVALID_REVIEW` (400).
- `FieldsResult.reviewed` mirrors the licence shape. Each primary field and each named additional field is `{current_value: string | null, is_edited: boolean}`. `vehicle_classes` is `{current_value: string[], is_edited: boolean}` because the ordered collection is reviewed as one form field. `ReviewUpdate.fields` carries primitive primary values, `vehicle_classes: string[]`, and an additional-information value map; the client cannot set edited flags.
- Both routes return `Cache-Control: no-store`. The browser capability remains in memory only and is never included in a URL or persisted in browser storage.
- The repository writes the review atomically only when the exact current document and extraction are still live. Delete and expiry win over a late save. A successful read/extract never silently replaces a saved review.

## Frontend behavior

- The existing **Read document** action performs reading, then Phase 3 extraction, then loads the review view. The right panel changes from placeholders to an accessible form with full name, licence number, birth/issue/expiry dates, address, vehicle classes, issuing authority, and extracted additional information.
- The original document remains visible beside the form. A non-null source field exposes its source page. Extraction warnings remain visible; a correction is labelled as user-edited rather than document evidence.
- Form state stays local until **Save changes**. The UI shows unsaved changes, disables conflicting operations while reading/extracting/saving, supports reverting local unsaved edits, preserves a failed save for retry, and presents safe API errors.
- A new upload or removal clears all local review state. A fresh browser session still cannot restore the private document without its in-memory capability.

## Verification and boundary

- Backend tests use no live OpenAI calls and cover default derivation, correction persistence/reload, intentional clears, original extraction preservation, validation, capabilities, and delete/expiry save races.
- Frontend tests/build checks cover validated untrusted API responses, read-to-populated form, edited/unsaved/saved/error states, keyboard form interaction, and small-screen layout. A live sample exercise may use the already configured key only after offline checks.
- Phase 4 stops after review/edit/save. Do not begin Phase 5 document Q&A.
