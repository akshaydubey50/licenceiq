# Phase 8: submission package contract

## Goal

Prepare a reproducible local submission package for the assessment: accurate project documentation, a reviewer-friendly demo runbook, a pre-submission checklist, a safe source archive, and current local verification evidence. The assessment accepts local setup instructions when no deployment URL is available.

## Authorized scope

- Confirm the README covers the technology stack, architecture, setup/run steps, AI approach, technical decisions, limitations, and AI development tools.
- Write a 5-10 minute recording runbook that demonstrates only implemented behavior with the two supplied fictional individual-crop samples.
- Write a submission checklist that separates verified local artifacts from human actions such as recording a video or sharing a repository/ZIP.
- Produce a local source archive that includes source, lockfiles, documentation, examples, and fictional samples while excluding secrets, private runtime data, installed dependencies, caches, and build outputs.
- Repeat the relevant existing local checks and record observed results without claiming that a clean machine, public deployment, or final video has been completed unless it is actually done.

## Boundaries

- Do not deploy publicly, create accounts, publish a repository, send a submission, or change the application runtime behavior in this phase. After the user's explicit request to complete Phase 8, a local captioned recording using only the fictional sample is permitted; it must not be uploaded or shared automatically.
- Do not include `.env`, `frontend/.env.local`, private `backend/.data`, `.runtime`, `.cache`, virtual environments, `node_modules`, `.next`, logs, or any API key in an archive or screenshot.
- Use only the fictional individual licence crops for local demo verification. Their visible contents are demonstration data, not an accuracy benchmark or real identity data.
- Keep the existing local temporary-file storage and per-document capability behavior documented honestly. MinIO and JWT work remain outside this phase.

## Acceptance evidence

- The submission documents use verified project commands and paths, distinguish current evidence from required candidate actions, and contain no secrets.
- The safe archive can be inspected to confirm required source/config/documentation files are present and excluded private files are absent.
- Backend and frontend quality commands complete successfully against the final source tree, with their results recorded.
- The phase report lists outstanding human actions: review the completed local video, choose ZIP versus hosted repository delivery, and optionally deploy to a suitable secured target.
