# LicenceIQ submission checklist

Use this checklist to package the completed local demo without claiming a
public deployment or repository publication that has not actually been
completed.

## Project evidence already available locally

- [x] Source code is present in this repository, including `frontend/` and
  `backend/`.
- [x] Local setup instructions, architecture, provider boundaries, commands,
  and limitations are documented in [README.md](../README.md).
- [x] The supplied fictional individual crops and their provenance notes are
  available in [samples/README.md](../samples/README.md).
- [x] Phase reports and contracts for the completed local build are available
  under `docs/`, including [Phase 7](PHASE_7_REPORT.md).
- [x] The local workflow covers upload/preview, read/extract, source evidence,
  review save, grounded Q&A, abstention, source navigation, and document
  removal.

These items are repository evidence. They do not mean that a public URL or
hosted environment exists.

## Candidate actions before submission

- [ ] Re-read the [README setup instructions](../README.md#run-locally) and
  start the backend and frontend locally.
- [ ] Confirm the local app opens at `http://127.0.0.1:3000` and the header
  reports **Backend connected**.
- [x] A captioned 5:18 local recording is available at
  `dist/LicenceIQ-demo-2026-09-20-captioned.webm`. It uses one individual
  fictional crop and removes its document at the end.
- [ ] Watch the finished video in full before sharing it. Confirm it shows the complete safe flow:
  upload, read/extract, source comparison, review/save, a direct question, a
  paraphrased question, an unsupported-question abstention, source navigation,
  removal, and architecture/limits.
- [ ] Make a ZIP of the source repository or publish an authorized repository
  link, following the assessment’s requested delivery method.
- [ ] Include the README and the demo-video link/file in the final delivery.
- [ ] Before sharing the ZIP or repository, check that ignored local settings,
  `.env` files, provider keys, temporary document storage, recordings of
  secrets, and unrelated personal files are excluded.

## Optional deployment

Deployment is not required for this local assessment. No hosting target or
account is configured by this project.

- [ ] If a deployment is explicitly requested later, choose and configure a
  hosting target before claiming a URL.
- [ ] Add public-hosting safeguards before exposing the app: authentication,
  secure storage, rate limits, scanning, stronger operational controls, and
  appropriate privacy review.
- [ ] Test the deployed URL separately from the local application, then include
  it only if it is working and authorized for sharing.

## Final pre-send check

- [ ] The recipient can access either the ZIP or the authorized repository
  link.
- [ ] The video is playable, within the requested 5–10 minute range, and uses
  only fictional samples.
- [ ] The README is included and its local run instructions match the delivered
  source.
- [ ] Any claims about tests or verification match the evidence in the README
  and phase reports; do not add unverified counts or accuracy claims.
- [ ] The submission does not claim that a public deployment or public URL
  exists unless one has actually been created and verified.
- [ ] No secrets, tokens, environment files, private documents, or temporary
  storage data are included.
- [ ] The final message identifies the source-code location and demo-video
  location clearly, without disclosing credentials.

## Local setup reference

From the repository root, follow the commands in the README:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local

cd backend
uv sync --frozen --python 3.11
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Do not overwrite existing local environment files when repeating setup. The
root `.env` holds the server-only provider key for scanned-image OCR; keep it
out of recordings, archives, repositories, and messages.
