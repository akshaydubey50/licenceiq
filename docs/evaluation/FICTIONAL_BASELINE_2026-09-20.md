# First live fictional evaluation baseline

Run: `licenceiq-gold-v0-20260920T083734177041Z`.

[Open the experiment in Langfuse](https://jp.cloud.langfuse.com/project/cmu9id1yp0006ad0csoyxoff3/datasets/cmu9j6kd0003ead0d8fnfytg5/runs/258e5cdd-c96c-47cb-b8b7-f4598bb13891).

All ten cases ran through the actual OCR, extraction and document Q&A services using the two
supplied fictional samples. No case produced a provider/runtime error. This does not mean all
answers were correct: three of eight answerable questions passed the reference-and-citation check.

## Results

| Metric | Score | Applicable cases |
| --- | ---: | ---: |
| Evidence Recall@3 | 0.2500 | 4 |
| Evidence Recall@5 | 0.5000 | 4 |
| Mean reciprocal rank | 0.1458 | 4 |
| Citation support rate | 0.3750 | 8 |
| Abstention accuracy | 1.0000 | 2 |
| Direct-path accuracy | 0.7500 | 4 |

Evaluator: `fictional-gold-v0.2`. Numeric reference checks normalize date format, case,
punctuation and whitespace. Multi-line source checks require coverage of every expected fragment.
Applicable provider failures would score zero; non-applicable metrics are omitted.

## Observed failures and next work

- The residence question returned the holder's name through the direct path. Review intent
  detection precedence so mentioning the holder does not turn an address question into a name lookup.
- The postal-code follow-up retrieved an address heading but missed the postal-code line in its
  eight selected blocks. Review conversation rewriting and retrieval of adjacent address lines.
- Expiry, vehicle classes and issuing authority returned `UNAVAILABLE` despite relevant evidence
  being in the selected blocks. Investigate generation, answer validation and guardrail decisions
  separately; the final envelope alone does not identify which stage rejected an answer.
- The issuing-authority case took retrieval rather than its expected structured lookup route.
  Review the supported intent variants alongside the unavailable-answer problem.

Keep this run as the baseline. After application fixes, rerun the same reviewed dataset and compare
experiments. Do not change expected answers merely to improve scores.

## Verification and limits

- Read-back from Langfuse confirmed ten outputs, 26 per-item scores and six aggregate scores
  exactly matching the local report. The API represents experiment output as JSON text, which was
  decoded before comparison.
- 40 focused offline tests passed; Ruff and focused mypy checks passed for evaluation scripts.
- Models: `gpt-4.1-mini` for OCR, extraction and Q&A; `text-embedding-3-small` for embeddings.
  Configured question guardrails were enabled. Application tracing was disabled inside the adapter;
  the separate experiment deliberately exports only reviewed fictional inputs, outputs and evidence.
- Runs use temporary filesystem storage and capability access. They do not test browser/API auth,
  Postgres or MinIO. No production application service was changed to improve this baseline.
- Scores are deterministic reference checks, not an LLM judge or a general hallucination guarantee.
  Two samples and ten questions cannot establish production accuracy. The first question for each
  sample includes OCR/extraction preparation time; token usage and cost are not reported.

The local full report and read-back verification are in the ignored `.runtime/evaluations/`
directory with this run's name. Reproduce from `backend` with:

```powershell
uv run python -m scripts.run_fictional_gold_experiment --run
```
