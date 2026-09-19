# LicenceIQ demo script (about 7 minutes)

This script demonstrates the local assessment build using one supplied fictional
licence crop. It is a guided product walkthrough, not an accuracy benchmark or
a claim about real driving licences.

## Before recording

- Start the local services from the repository root as described in the
  [README](../README.md#run-locally). Keep the backend and frontend terminals
  visible only if the recording needs to show local setup; do not show `.env`
  files, provider keys, or terminal output containing private information.
- Open `http://127.0.0.1:3000` in a clean browser window and confirm the
  development header says **Backend connected**. Close unrelated tabs,
  notifications, downloads, and password-manager pop-ups.
- Use one individual crop only: `samples/fictional_delhi_licence.png` or
  `samples/fictional_maharashtra_licence.png`. Do not upload the composite
  image, because it contains two documents. The images are fictional samples;
  their visible text is not production data or proof of OCR accuracy. See
  [sample notes](../samples/README.md).
- Record at a readable zoom and pause briefly after each state change. If the
  OCR/AI key is unavailable, restore the local setup before recording rather
  than substituting screenshots or invented results.

## Suggested narration and actions

### 0:00–0:35 — Introduce the scope

**Say:** “LicenceIQ is a local workspace for reading, reviewing, and
understanding one driving-licence document. This recording uses a supplied
fictional sample. It is not an authenticity check and it does not demonstrate
real-person data.”

Show the empty local app and the **Backend connected** indicator. Mention that
the app accepts PDF, PNG, JPG, and JPEG files, and that the workflow keeps the
active document private to this browser session.

### 0:35–1:20 — Upload and preview one fictional document

Choose one of the individual files above and select **Upload document**. Wait
for the private preview and upload state to finish.

**Say:** “I am uploading one individual fictional crop. The app validates the
file and shows a private preview; it does not use a public file link.”

Do not read personal-looking values aloud or enlarge them unnecessarily. Point
out only that the preview is the source document being reviewed.

### 1:20–2:10 — Read and extract source-backed fields

Select **Read document** and wait for the reading/extraction view.

**Say:** “Reading is an explicit action because scanned images can be sent to
the configured OCR provider. LicenceIQ then presents extracted fields with
their source evidence, rather than treating model output as authoritative.”

Show the extraction and, in development, open the raw-text inspector if it is
available. Compare one displayed field with the matching text in the preview.
Avoid calling this a correctness score; say that visual review remains part of
the workflow.

### 2:10–3:05 — Review, correct, and save

Choose a field that can be safely changed for the demonstration, make a clearly
described reviewer correction, and select **Save review**. Confirm the saved
state, then show that the original extracted value and its source evidence are
still visible separately.

**Say:** “A reviewer correction is stored as a reviewer value. It does not
overwrite the extracted source value or turn the correction into document
evidence.”

Do not use the correction as the basis for a later document-answer claim.

### 3:05–4:05 — Ask a direct question

In **Ask this document**, ask: “What is the licence number?”

Show the answer and its citation/source control.

**Say:** “This is a direct field question. The answer comes from the immutable,
evidence-backed extraction for this active document, rather than from the
reviewer edit.”

### 4:05–5:05 — Ask a paraphrased question

Ask a broader paraphrased question such as: “Until when is this document valid
to drive?”

Show the grounded answer and its citations.

**Say:** “For broader phrasing, the app searches a bounded temporary index of
this document’s reading blocks, then returns an answer only when it can cite
the selected source evidence. The first broader question can take longer while
that temporary index is prepared.”

### 5:05–5:40 — Demonstrate abstention

Ask: “What is the holder’s passport number?”

Show the unavailable response.

**Say:** “That information is not in this document, so the system abstains
instead of inventing an answer.”

### 5:40–6:20 — Open the cited source

Select the source control beside an extracted field or an answered question.
Show the preview’s focused-source state and the stored evidence excerpt.

**Say:** “The source control is limited to the active document and exposes the
stored excerpt used to support the value. It does not claim pixel-perfect OCR
highlighting, because OCR geometry is usually unavailable.”

### 6:20–6:45 — Remove the document

Select **Remove document** and wait for the empty workspace state.

**Say:** “Removal clears the stored document, reading, extraction, reviewer
values, and temporary semantic index for this local demo document.”

### 6:45–7:30 — Explain architecture and current limits

Use the README’s architecture diagram or briefly show the repository layout.

**Say:** “The browser talks to a local Next.js interface and FastAPI service.
The service validates uploads, keeps temporary private document state, retains
source evidence, and keeps reviewer corrections separate. Native PDF text is
read locally; scanned pages can use the configured OpenAI OCR and question
providers. Broader questions are restricted to the active document’s bounded
temporary retrieval state.”

Close with the main limits: this is a localhost demo; it has no user accounts,
public deployment, malware scanning, authenticity verification, or broad OCR
accuracy benchmark. Source navigation shows an excerpt and focused-page state,
not a guarantee of pixel-exact highlighting. Refer reviewers to the
[README](../README.md#known-limitations) for the complete limitations.

## Recording recovery notes

- If a read or broader question fails, do not edit a response or narrate a
  result that did not appear. Resolve the local provider/configuration issue and
  restart the affected portion of the recording.
- If removal fails, leave the visible error and retry only after explaining
  that the document remains visible until server-side removal succeeds.
- Do not show `.env`, access tokens, API keys, browser developer tools,
  temporary storage folders, or any non-fictional document.
