# Routing record: four frontend design options

Date: 19 September 2026.

## Authorized scope

Expand the standalone frontend exploration into four genuinely different, clickable design directions covering the documented LicenceIQ journey and recovery states. Files are confined to mockups/licenceiq-options/, its new ZIP, this routing record and local preview/check artifacts under .runtime/licenceiq-options/. No application frontend/backend implementation or phase advancement is part of this task.

The project's build plan, existing mockup, sample descriptions, required coding-orchestrator skill and installed Minimal skill informed the work. Minimal's clarity, source visibility, typography and accessibility principles were retained while the user's explicit request for four different designs justified different colours, layouts and visual personalities.

## Assessments and actual dispatch

The installed select_route.py helper was called through its choose_route function with the installed personal model map and model/effort availability from the current collaboration tool metadata.

| Work unit | Uncertainty | Scope | Reasoning | Verification | Risk | Helper result | Actual execution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Shared screens, state, source integrity and integration | 1 | 2 | 2 | 1 | Low | 6/8, strong, gpt-5.6-sol / high | Existing coordinator stayed on its current model; no model-switch claim |
| Atlas and Relay layout styles | 1 | 1 | 1 | 1 | Low | 4/8, balanced, gpt-5.6-terra / medium | /root/atlas_relay_design, explicit gpt-5.6-terra / medium |
| Prism and Folio layout styles | 1 | 1 | 1 | 1 | Low | 4/8, balanced, gpt-5.6-terra / medium | /root/prism_folio_design, explicit gpt-5.6-terra / medium |

Evidence: product flows and fixtures were known; the new work was independent static UI. The shared layer required coordinating evidence, corrections, save state, file preview, conversation isolation and many recovery transitions. Each layout worker had a bounded CSS-only ownership contract. At most two workers ran concurrently, fresh self-contained handoffs were used, and there was no nested delegation.

## Integration and correction

- Atlas/Relay used two implementation attempts: initial styles, then integration corrections for tablet navigation, contrast, image proportions, mobile step visibility, heading spacing and readable form text.
- Prism/Folio used three implementation attempts: initial styles; integration corrections for the console shell, composer, footer and responsive headers; then a precise desktop sidebar-navigation correction after an actual click was intercepted by the overlapping main heading.
- Shared coordinator work used two implementation rounds: initial complete state layer, then navigation/async-upload and accessibility-reference cleanup.
- No model escalation occurred. Each worker retained its actual initial model and effort. No new worker was used to reset attempt counters.

The first acceptance run exposed Prism's overlapping navigation after 46 successful checks. The failing click trace was retained in tool output and the CSS was corrected. The final full run passed.

## Observed validation

- JavaScript syntax check passed.
- 102 grouped browser checks passed in isolated Chromium.
- Fourteen scenario screens were checked at 320, 390, 768, 1024 and 1440px for each direction, with no horizontal page overflow.
- Per-direction interaction checks covered eleven fields, evidence/qualifiers, real calendar validation, edits, saves, separate-layer export, original-source answers after correction, inert HTML questions, unsaved-change protection, reset, sample isolation, missing restrictions, reprocessing, cancellation, replacement/removal recovery, expiry and local preview.
- No JavaScript errors, external network requests or application API requests were observed in the final run.
- All four designs and prepared answers worked from a direct local file URL.
- Final desktop/mobile and supporting-state screenshots were generated. The coordinator inspected the actual renders and a four-direction comparison image.

This validates the prototype, not production OCR, extraction, persistence or Q&A. Those actions are deliberately simulated for the fictional examples. Real files preview locally without sample extraction. Files under frontend/ and backend/ were not edited by this task; simultaneous application work remains separate.
