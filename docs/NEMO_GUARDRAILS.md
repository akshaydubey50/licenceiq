# NeMo Guardrails for document Q&A

LicenceIQ can apply local NeMo Guardrails before a question reaches retrieval and before an answered result is returned. The default is disabled so the original assessment demo keeps its existing behaviour.

Enable it in the ignored root `.env` file:

```dotenv
LICENCEIQ_QUESTION_GUARDRAILS_ENABLED=true
LICENCEIQ_QUESTION_GUARDRAIL_TIMEOUT_SECONDS=2
```

## What the rails do

- Reject prompt-injection and prompt-control wording before direct field lookup, embeddings, or the answer provider run.
- Reject attempted system or developer prompt leakage in a returned answer.
- Allow legitimate licence values, including personal data that the authorised reviewer has requested.
- Fail closed with a controlled API error if enabled rails cannot initialise or finish inside their timeout.

The rails are local custom NeMo actions. They do not use an additional model or network service. They receive only the user question on input and the final proposed answer on output. OCR text, retrieved evidence blocks, extracted fields, credentials, and provider configuration never enter the rail.

## Grounding remains independent

NeMo enforces policy, not document truth. LicenceIQ continues to isolate retrieval to the active document, require citations from selected blocks, and reject provider answers whose meaningful terms do not occur in those cited blocks. When evidence is not sufficient, the API returns the existing unavailable response.

## Current implementation boundary

The installed NeMo version uses a deterministic local Colang custom-action flow for these checks. This is deliberately limited to the assessment's document Q&A boundary. It does not claim general-purpose moderation, jailbreak coverage, or a substitute for a broader red-team evaluation before public deployment.
