# LicenceIQ fictional question suites v1

These five local datasets turn the expected behaviour of LicenceIQ into reviewed, repeatable checks. They use only the supplied fictional Maharashtra and Delhi one-page licence samples. They are not an OCR benchmark and must never be seeded with real licence data, browser chats, access tokens, runtime identifiers, or provider traces.

| File | Coverage | Expected application outcome |
| --- | --- | --- |
| `01-happy-path.json` | Direct questions about structured licence fields | `ANSWERED` with source citation |
| `02-semantic-and-context.json` | Paraphrases, multi-field questions, summaries, and bounded follow-ups | `ANSWERED` with source citation |
| `03-neutral-unsupported.json` | Licence-related details that the document does not provide | `UNAVAILABLE` with no citation |
| `04-off-topic.json` | Clearly unrelated requests | `OUT_OF_SCOPE` with no citation |
| `05-prompt-injection.json` | Instruction override, hidden-prompt, role-message, and jailbreak attempts | HTTP 400 / `QUESTION_BLOCKED` and no provider work |

Each case separates the real request (`input`) from the human-reviewed expected behaviour (`expected_output`) and grouping information (`metadata`). `sample` refers only to one of the pinned fictional sample files. `prior_questions` models the previous user questions already held within the same document conversation; it must never cross documents.

## Review before Langfuse

The files are deliberately local drafts. Review every answer, source fragment, and safety expectation before creating or uploading a Langfuse dataset. After approval, publish one immutable dataset per file under `licenceiq/fictional-question-suites-v1/` and record the returned dataset version in a separate change. Do not upload this suite automatically.

## Local validation

From `backend`:

```powershell
uv run pytest tests/test_fictional_question_suites.py
```

The check is offline: it verifies schema shape, unique IDs, fictional-only samples, category coverage, and the response contract. It does not call OpenAI, Langfuse, Docker, or the running application.
