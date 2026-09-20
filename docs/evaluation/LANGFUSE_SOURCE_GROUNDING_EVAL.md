# Privacy-safe Langfuse source-grounding evaluation

This foundation checks LicenceIQ's answer envelope using only synthetic status labels and citation counts. It deterministically distinguishes grounded answers, safe unavailable or out-of-scope responses, uncited answers, and inconsistent citation states. It does not measure answer correctness, retrieval quality, OCR accuracy, or production behavior.

The application now creates a privacy-safe top-level `licenceiq.question` span for each Q&A turn and nests provider observations beneath it. Those spans omit inputs, outputs, document or user identifiers, and exception text. This evaluation remains separate from runtime tracing: its local dataset contains only fixed fixture names, `ANSWERED` / `UNAVAILABLE` / `OUT_OF_SCOPE`, integer citation counts, and expected safe categories.

## Local offline run

From `backend`, run:

```powershell
.\.venv\Scripts\python.exe scripts\source_grounding_eval.py
```

Expected output is one JSON summary with seven cases, seven passes, and zero failures. This default path does not import the Langfuse SDK, read credentials, or make a network call.

## Explicit Langfuse export

External export requires both the `--export-langfuse` CLI flag and a dedicated `LICENCEIQ_LANGFUSE_EVAL_EXPORT=true` environment opt-in. It also requires complete Langfuse credentials:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_BASE_URL`, set to the HTTP(S) URL for the selected Langfuse cloud region or self-hosted server

Set these in the shell or a local untracked environment file; never put their values in commands committed to the repository. A clean PowerShell run is:

```powershell
$env:LICENCEIQ_LANGFUSE_EVAL_EXPORT = 'true'
$env:LANGFUSE_PUBLIC_KEY = '<project-public-key>'
$env:LANGFUSE_SECRET_KEY = '<project-secret-key>'
$env:LANGFUSE_BASE_URL = 'https://cloud.langfuse.com'
.\.venv\Scripts\python.exe scripts\source_grounding_eval.py --export-langfuse
```

The script uses Langfuse Python SDK v4's local-data `run_experiment` path and a deterministic SDK evaluator. Local data still becomes external experiment data when export is enabled. The fixed experiment payload contains no licence image or text, question, answer, evidence excerpt, document or user identifier, access token, or environment secret.

## Focused verification

From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_grounding_eval.py -q
.\.venv\Scripts\python.exe -m ruff check scripts\source_grounding_eval.py tests\test_source_grounding_eval.py
.\.venv\Scripts\python.exe -m mypy scripts\source_grounding_eval.py
```

The tests use an in-memory fake experiment client. They do not require credentials or network access and do not create a Langfuse experiment.
