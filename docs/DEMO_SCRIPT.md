# LicenceIQ live-demo narration

**Recorded video:** `artifacts/recordings/live-demo-20260920T095515Z/LicenceIQ-Live-Demo-5m13.mp4`
**Duration:** 5 minutes 13 seconds
**Format:** spoken voice-over on the real browser recording. No slides, generated product screens, or real personal data.

## Delivery notes

- Start narration when the LicenceIQ landing page appears. Speak at a calm pace and pause while the live OCR or question response is processing.
- The video uses only the bundled fictional Maharashtra licence. It includes a disposable local demonstration account.
- Do not read the fictional licence number, address, date of birth, or any other document value aloud. Point out the source evidence instead.
- The last screen holds the successful sign-out confirmation. Use it for the closing sentence, then let the recording end naturally.

## Narration aligned to the video

### 0:00–0:18 — Introduce the application

> Hi, I’m Akshay. This is LicenceIQ, an AI-powered document-intelligence application for driving licences. The workflow is simple: upload one document, read it, extract structured information, let a person review it, and ask questions that stay grounded in that document. This recording uses only the fictional sample supplied for the assessment.

### 0:18–0:40 — Guest option

> The landing page gives two access paths. A guest can try a temporary workspace without registering, while a signed-in user works in a private account workspace. I am opening and leaving the guest path here to demonstrate that the option is available. For the rest of the recording, I will use an account so the document and review history are tied to one user.

### 0:40–1:22 — Sign-up, sign-out, and sign-in

> I create a local demonstration account, which takes me directly into an authenticated session. The account flow uses a server-side Argon2 password hash and a short-lived JWT held only in browser memory. I then sign out. The application revokes the server session before returning to the sign-in page. Finally, I sign in again to show the normal private-workspace flow.

### 1:22–1:55 — Upload the document

> I now select the fictional driving-licence image and upload it. The frontend accepts PDF, PNG, and JPG files up to the configured size limit. The backend validates the file before storing the original document privately in MinIO-compatible object storage. Document metadata, extraction evidence, review records, user details, sessions, and retrieval embeddings are persisted in PostgreSQL with pgvector.

### 1:55–2:32 — Read, OCR, and extract

> Reading is an explicit step, so the user controls when document content is processed. For an image such as this one, LicenceIQ uses the configured OpenAI vision service to read the page. It then extracts the full name, licence number, dates, address, vehicle classes, issuing authority, and any other relevant fields. The application keeps page-level reading evidence alongside the structured result, instead of treating an AI response as unquestioned truth.

### 2:32–3:02 — Verify the source

> Each extracted field includes a source control. When I select it, the application focuses the corresponding page and shows the evidence excerpt that supports the field. This gives the reviewer a direct way to compare the form with the uploaded licence.

### 3:02–3:30 — Review and save a correction

> The form is editable. I make a small formatting correction and save it. LicenceIQ deliberately keeps the reviewer’s value separate from the original model extraction and its source evidence. That separation makes it clear which values came from the document and which values were changed by a person.

### 3:30–4:00 — Direct question and citation

> Next, I ask a direct question: “What is the driving licence number?” The answer is returned with a source reference. Selecting the reference opens the related evidence in the document preview, so an answer can be checked immediately rather than trusted blindly.

### 4:00–4:32 — Broader grounded question

> I now ask a broader question: “What vehicles is this person authorised to drive, and what restrictions apply?” For these questions, LicenceIQ searches evidence from the active document only. It combines lexical matching with semantic retrieval using pgvector embeddings, then sends the selected evidence to the answer model. The result must remain supported by source evidence from this licence.

### 4:32–4:52 — Safe unavailable response

> Finally, I ask for the holder’s passport number. That information is not present in a driving licence, so the correct behaviour is to say it could not be found in the document. The application does not invent a value or add a citation where the evidence does not exist.

### 4:52–5:13 — Logout and close

> I end by signing out, which safely revokes the local session. LicenceIQ demonstrates the full assessment workflow: secure document upload, OCR and structured extraction, editable human review, source traceability, grounded document Q-and-A, and clear abstention when information is unavailable. The project was developed with OpenAI Codex as an AI-assisted development tool. Thank you for watching.

## Accuracy guardrails for the presenter

- Say **“fictional sample”**, **“source-backed evidence”**, and **“human review remains required.”**
- Do not claim identity verification, licence authenticity checks, QR validation, signature verification, legal driving-permission decisions, or production readiness.
- Do not reveal `.env` files, OpenAI keys, JWTs, document capability tokens, MinIO credentials, database contents, or provider request/response payloads.
