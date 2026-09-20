# Optional Langfuse observability

LicenceIQ can emit manual Langfuse observations for its AI provider calls. The integration is
disabled by default and remains a nonessential diagnostics sink: initialization, export, flush,
or shutdown failures never block OCR, extraction, retrieval, or document Q&A.

## Privacy contract

The integration does not use Langfuse's automatic OpenAI wrapper. It creates manual observations
without an input or output value and passes metadata through a fixed allowlist before the SDK sees
it. LicenceIQ never exports:

- document images, PDF bytes, OCR text, reading blocks, or extracted/reviewed field values;
- user questions, conversation history, rewritten questions, or generated answers;
- document, evidence-block, capability, user, session, request, or access-token identifiers;
- authorization values, API keys, provider credentials, or arbitrary exception text; or
- provider prompts, responses, or raw model payloads.

The permitted fields are fixed operation stage/type, a bounded model label, success/failure,
the fixed `provider_error` category, duration in milliseconds, selected-block/citation counts,
token counts if a future provider contract exposes them safely, and approved boolean flags.
Current provider contracts do not expose token usage, so LicenceIQ does not report token counts.

Failures are closed without forwarding the exception object or traceback to Langfuse. This avoids
OpenTelemetry automatically recording an exception message that could contain private content.

## Local setup

Create a Langfuse project and keep its keys only in the ignored root `.env` file. Set:

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-your-project-key
LANGFUSE_SECRET_KEY=sk-lf-your-project-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_IO=false
```

Use the URL for your Langfuse Cloud region or your self-hosted root. Telemetry stays disabled if
the enable flag, either key, or the base URL is missing or blank. Production configuration also
requires an HTTPS Langfuse URL. Never use `NEXT_PUBLIC_*` variables for these settings and never
commit the populated `.env` file.

## Trace coverage

Manual observations cover these provider operations:

| Observation | Langfuse type | Private values omitted |
| --- | --- | --- |
| `licenceiq.ocr` | generation | page image and OCR lines |
| `licenceiq.extract` | generation | reading context and extracted candidates |
| `licenceiq.embed` | embedding | source blocks, questions, and vectors |
| `licenceiq.query_rewrite` | generation | current/history questions and rewritten query |
| `licenceiq.answer` | generation | question, selected text, answer, and block IDs |

The answer observation can include only selected-block count, citation count, and an availability
flag. Retrieval is visible through its embedding calls; the deterministic ranking function does
not emit a separate external observation.

## Verification boundary

Offline tests verify disabled and incomplete configuration, forced input/output capture disablement,
metadata allowlisting, secret-bearing exception redaction, and fail-open behavior. A live trace has
not been sent or inspected because no user project credentials are included. After configuring a
project, run the fictional-sample workflow and audit the resulting observations in Langfuse before
claiming live export, dashboard, retention, regional routing, or access-control behavior.

Implementation follows Langfuse's current Python v4 manual observation and source-side masking
guidance: [SDK overview](https://langfuse.com/docs/observability/sdk/overview),
[masking](https://langfuse.com/docs/observability/features/masking), and
[trace practices](https://langfuse.com/docs/observability/best-practices).
