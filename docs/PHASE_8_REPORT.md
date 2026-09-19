# Phase 8: local submission package

Status: complete on 20 September 2026. This phase prepares the assessment handoff, including a local captioned demo recording, without claiming that a public deployment, published repository, or final external submission exists. The boundary is defined in [the Phase 8 contract](PHASE_8_CONTRACT.md).

## What changed

- Added [a 6–8 minute demo script](DEMO_SCRIPT.md) that shows the implemented upload, read/extract, review/save, direct and paraphrased questions, abstention, source navigation, removal, architecture, and limits flow using only one supplied fictional crop.
- Added [a submission checklist](SUBMISSION_CHECKLIST.md) that separates local evidence from candidate actions and optional deployment work.
- Created `dist/LicenceIQ-source-2026-09-19.zip`, a source-only archive generated from an allowlist of project source, lockfiles, documentation, configuration examples, and fictional samples.
- Created `dist/LicenceIQ-demo-2026-09-20-captioned.webm`, a 5:18 captioned recording of the actual localhost workflow using the fictional Delhi crop. It shows upload, read/extract, a reviewed edit/save, direct answer, paraphrased semantic retrieval, abstention, source navigation, and removal.
- Updated the README and build plan with an honest local-submission handoff state.

The archive excludes `.env`, `frontend/.env.local`, private document storage, runtime artifacts, caches, virtual environments, dependencies, build output, and logs. Its inspection found 169 entries, required project files, and no excluded path component.

## Routing and development tools

The [coding-orchestrator workflow](DEVELOPMENT_ROUTING.md) assessed demo documentation and checklist work at 4/8 with low risk, selecting the balanced route. The coordinator retained the contract, archive, README, verification, and reporting work.

| Work unit | Assessment | Actual execution | Attempts / escalations | Outcome |
| --- | --- | --- | --- | --- |
| Demo script and submission checklist | [4/8, low risk](routing/phase-8-submission-assessment.json) | `/root/phase8_demo_docs`, `gpt-5.6-terra` / `medium` | 1 / 0 | Accepted after coordinator review |
| Contract, archive, setup audit, verification, and reporting | Direct coordinator work | Coordinator model unchanged | 1 / 0 | Accepted |

## Verification

| Check | Observed result |
| --- | --- |
| Backend test suite | 185 tests passed |
| Backend Ruff check and strict mypy | Passed |
| Backend format and lock checks | 41 files already formatted; lock check passed |
| Frontend lint, typecheck, and format | Passed with the required Node 24 runtime |
| Frontend production build | Webpack build passed: compile, types, static generation, and route output |
| Local services | FastAPI `/health` returned `200` with `{"status":"ok"}`; frontend root returned `200` |
| Source archive inspection | 169 entries; required source/documentation/sample files present; no secret, runtime, dependency, cache, build, or log paths found |
| Documentation review | README requirements coverage, local commands, sample paths, and demo/checklist links inspected |
| Demo video recording | 318.2 seconds (5:18), 1440×900 WebM, 21,263,148 bytes; server-only provider key and temporary document capability were never displayed |
| Demo video playback | Media metadata plus a frame at 180 seconds checked; the frame showed the live cited-answer interface and semantic-retrieval caption |
| Demo cleanup | Recording result confirmed removal of its temporary fictional document; API health remained `200` afterwards |

The sandbox’s system Node 20.11 could not resolve the workspace path and does not meet the project's preferred runtime. The frontend checks were rerun with the available Node 24 runtime and passed. This was a local verification-environment condition, not an application change.

## Remaining candidate actions

1. Watch `dist/LicenceIQ-demo-2026-09-20-captioned.webm` in full before sharing it.
2. Deliver `dist/LicenceIQ-source-2026-09-19.zip` and the video, or publish an authorized repository, then include the README with the submission.
3. Deploy only if a suitable target and the required public-hosting safeguards are explicitly arranged and verified.

## Remaining limits

- This is still a localhost demo with temporary private filesystem storage and a per-document capability, not MinIO storage or JWT user accounts.
- The source archive is local and ignored by version control. It is a handoff artifact; it is not a published repository or public download.
- No public hosting, email, repository publication, or external submission was performed in this phase.
