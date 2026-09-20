# Langfuse observability and evaluation

LicenceIQ can emit manual Langfuse observations for its AI provider calls. The integration is
disabled by default and remains a nonessential diagnostics sink: initialization, export, flush,
or shutdown failures never block OCR, extraction, retrieval, or document Q&A.

## Privacy contract

The integration does not use Langfuse's automatic OpenAI wrapper. It creates manual observations
without an input or output value and passes metadata through a fixed allowlist before the SDK sees
it. Normal application tracing never exports:

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

## Upload the reviewed fictional evaluation dataset

The local fictional gold file is a separate, reviewed evaluation asset. It contains only the two
provided fictional samples and is never created from production traces. It can be uploaded to the
Langfuse dataset named `licenceiq/fictional-gold-v0` only after that dataset has been created in
the Langfuse dashboard.

From the `backend` directory, first validate the upload payload without reading credentials or
contacting Langfuse:

```powershell
uv run python scripts/upload_fictional_gold_dataset.py
```

The command must report `mode: dry-run`, `items: 10`, and `valid: true`. To add the reviewed
fictional items, set the three Langfuse values in the ignored root `.env`, then run:

```powershell
uv run python scripts/upload_fictional_gold_dataset.py --upload
```

The uploader reads only `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`
from that file. You can point at a different local env file with `--env-file PATH`; process
environment values override file values. Every upload requires the explicit `--upload` flag.
It rejects non-fictional privacy markers, runtime document/trace identifiers, raw bytes, and local
paths before it can contact Langfuse.

## Run the fictional application experiment

After uploading the dataset, use the experiment runner from `backend`:

```powershell
uv run python -m scripts.run_fictional_gold_experiment
uv run python -m scripts.run_fictional_gold_experiment --run
```

The first command validates locally. `--run` uses the configured OpenAI key and models, checks
that the hosted ten items exactly match the approved local dataset, and creates an experiment
linked to `licenceiq/fictional-gold-v0`. The final output includes the experiment URL and a local
report under the ignored `.runtime/evaluations/` directory. Refresh the dataset's **Experiments**
tab after completion. Each new run has a unique name so results remain comparable.

The application adapter runs actual upload validation, OCR, extraction, query rewriting, direct
lookup, hybrid retrieval, answer validation, and configured guardrails. It uses temporary filesystem
storage and capability access, not the user's existing database, MinIO bucket, documents or account.
Only the two fixed fictional sample files are accepted, with their image hashes checked before use.
This is a service-level document-Q&A benchmark, not a browser, authentication or deployment test.

Each sample is read/extracted once per run. All ten question cases run sequentially. The task receives
only the question, permitted prior questions, and sample selector; expected answers are used only by
the evaluator. Evaluation-only capture records the actual direct path and ranked selected blocks.
This preserves the normal application's privacy contract. The approved fictional experiment exports
its question, final answer and selected/cited evidence, but no document access tokens, storage paths,
runtime document identifiers, user information or raw images.

Scores use the same code locally and in Langfuse:

- Evidence Recall@3 and Recall@5 measure the fraction of expected source fragments found in the
  first three/five selected blocks. MRR uses the first relevant block. These metrics apply to the
  four designated retrieval cases. Multi-line fields can span multiple blocks.
- Citation support applies to the eight answerable cases and requires expected answer content and
  coverage of all expected page/text fragments across the actual cited evidence.
- Abstention accuracy applies to the two unavailable/off-topic cases.
- Direct-path accuracy applies to the four designated structured lookup cases and requires evidence
  plus actual direct lookup with no retrieval.

Provider failures remain visible with a fixed error code and count as zero in applicable metrics.
Non-applicable scores are omitted rather than averaged as zero. Numeric date formats, case,
whitespace and punctuation are normalized for source/reference checks; fixed abstention messages
still use exact matching. These are deterministic reference checks, not an LLM judge or a proof that
every possible extra claim is supported. A ten-case set cannot establish general production accuracy.
The first question for a sample also pays OCR/extraction preparation time, so per-item durations are
not a controlled comparison of generation latency. Token usage/cost is not provided by this runner.

## Verification boundary

Offline tests verify disabled and incomplete configuration, forced input/output capture disablement,
metadata allowlisting, secret-bearing exception redaction, and fail-open behavior.

The first live fictional experiment completed on 2026-09-20. Read-back verified all ten outputs,
26 per-item scores and six aggregate scores against the local report. Its results include failures
in answer quality, even though no provider calls failed. See the
[baseline report](evaluation/FICTIONAL_BASELINE_2026-09-20.md) for the original results. The
[Q&A fix report](evaluation/QA_FIXES_2026-09-20.md) records the changes, improved live scores and
remaining repeatability limitations. Both final-code experiments were verified against their
local outputs and scores; the earlier heading-citation miss remains visible alongside the passing run.
This verifies the isolated fictional evaluation export; it does not establish production tracing,
retention policy, account access control or a general production accuracy level.

Implementation follows Langfuse's current Python v4 manual observation and source-side masking
guidance: [SDK overview](https://langfuse.com/docs/observability/sdk/overview),
[masking](https://langfuse.com/docs/observability/features/masking), and
[trace practices](https://langfuse.com/docs/observability/best-practices).
