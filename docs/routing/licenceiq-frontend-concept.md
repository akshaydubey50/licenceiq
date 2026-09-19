# LicenceIQ standalone frontend concept — routing and scope

Authorized by the user: inspect the current LicenceIQ frontend and build a separate HTML/CSS/JavaScript mockup using the installed Minimal skill. Application frontend/backend changes and later-phase implementation are outside this task.

## Assessment and dispatch

The project-required coding-orchestrator and its routing rubric were read. Current exposed capabilities included Luna, Terra, Sol and Astra with their documented tool-supported effort levels.

| Work unit | Scores: uncertainty / scope / reasoning / verification | Evidence | Route and actual execution |
| --- | --- | --- | --- |
| Current UX and product constraints | 1 / 1 / 1 / 1 = 4, low risk | README and current component differ; inspect source and contracts, preserve planned/implemented distinctions | Installed helper recommended `gpt-5.6-terra` / `medium`; actually dispatched to `/root/licenceiq_ux_audit` with a fresh handoff |
| Standalone visual mockup and interactions | 1 / 1 / 1 / 1 = 4, low risk | Bounded static prototype, local assets, sample switching and review states; browser acceptance checks | Balanced assessment; direct coordinator execution while the read-only audit ran independently |
| Focused product/UX review of the mockup | Same balanced route | Check provenance, sample isolation and desktop/mobile screenshots against the agreed product constraints | Follow-up to the same Terra/medium agent; no writes or nested delegation |

The coordinator retained its current session model. Helper output was a recommendation, not a model switch. At most one worker ran; no escalation was used. The implementation received a focused polish pass for mobile address wrapping, source alignment and small-screen layout.

## Findings and boundaries

Actual current code implements upload, private image/PDF preview, replacement/removal and recovery. Extraction/review/Q&A remain placeholders. The prototype intentionally illustrates the future flow with the supplied fictional licence samples.

All edits by this task are confined to the new mockup, this routing note and a dedicated local QA/preview directory under `.runtime/licenceiq-mockup`. Existing application files and the global skill were not edited. No OCR/LLM/backend requests were made by the mockup.

## Validation

- JavaScript syntax check passed.
- All 17 local isolated browser acceptance checks passed, covering samples/assets, keyboard navigation, source excerpts, original-versus-corrected values, save/reset, document isolation, missing restrictions, export, invalid-file recovery, custom-file isolation, empty state, tab keyboard behavior, preview controls and refresh reset.
- Desktop and mobile screenshots were visually inspected. Widths 320, 390, 768, 1024 and 1440 were checked for horizontal overflow and address clipping.
- Opening the standalone HTML directly with a file URL also passed sample rendering and prepared-answer interaction checks; no web server is required for the bundle.
- Network checks reject external requests and application API access. No JavaScript errors were observed.
- Independent review found no material blocker; highlighted mobile textarea/source-alignment items were addressed before final QA.

Artifacts: `mockups/licenceiq-minimal/`; QA details and script: `.runtime/licenceiq-mockup/`.

Validation concerns the static prototype, not production OCR, extraction, save durability or answer quality. The existing app's build/test suite was not rerun because its source and dependencies were not changed.
