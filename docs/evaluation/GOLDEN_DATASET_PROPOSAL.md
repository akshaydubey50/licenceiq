# LicenceIQ fictional golden dataset

## Goal

Create a small, repeatable regression dataset for the supplied fictional Maharashtra and Delhi licences. It will measure whether LicenceIQ retrieves the right immutable evidence, returns a grounded answer, and abstains when the document cannot support an answer.

This is a quality baseline for the assessment demo. It is not an OCR benchmark, a claim about real licences, or a dataset for production documents.

## Source and privacy boundary

- Use only `samples/fictional_maharashtra_licence.png` and `samples/fictional_delhi_licence.png`.
- Keep the local golden file in the repository for review.
- The Langfuse dataset contains only these fictional cases. Do not upload a real licence, browser chat, access token, runtime document identifier, or production trace content.
- Langfuse tracing continues to omit inputs and outputs. The golden dataset is the explicit, reviewed evaluation source.

## Implemented v0 distribution: 10 cases

| Area | Cases | Purpose |
| --- | ---: | --- |
| Direct structured fields | 2 | Licence number and holder name; must use evidence-backed extraction without retrieval. |
| Paraphrased retrieval | 3 | Expiry, residence/address, and vehicle-authorisation wording; must find the right reading block when the wording differs. |
| Conversation-aware retrieval | 1 | A follow-up that depends only on the preceding user question and stays inside the same document. |
| Extraction evidence | 2 | Issue date and issuing authority; validates the field value and source page. |
| Supported absence | 1 | Occupation or profession; must return the fixed unavailable response because it is absent. |
| Out-of-scope handling | 1 | A clearly unrelated question; must return LicenceIQ scope guidance without retrieval. |

Both fictional documents appear in direct, paraphrased, and extraction cases. The cases include one request that needs semantic retrieval and one that must abstain, because those are the current behavior risks already seen in this project.

## Implemented item schema

```json
{
  "id": "fictional-delhi-expiry-paraphrase-v0",
  "input": {
    "sample": "fictional_delhi_licence",
    "question": "How long is this licence valid?",
    "prior_questions": []
  },
  "expected_output": {
    "status": "ANSWERED",
    "answer_equals": null,
    "answer_contains": ["09-04-2038"],
    "citation_required": true,
    "minimum_citations": 1,
    "source_page": 1,
    "source_locator_text": ["Valid Till : 09-04-2038"]
  },
  "metadata": {
    "task": "paraphrased_retrieval",
    "intent": "expiry",
    "requires_retrieval": true,
    "expected_direct_lookup": false,
    "include_in_retrieval_rank_metrics": true
  }
}
```

`input` contains only what the application receives. `expected_output` contains the human-reviewed result. `metadata` supports grouping and metrics without becoming model context.

## Metrics

| Metric | Calculation | Decision it supports |
| --- | --- | --- |
| Evidence Recall@3 | Fraction of expected source fragments covered by the first three selected blocks. | Whether retrieval finds all required evidence. |
| Evidence Recall@5 | Same check for the first five selected blocks. | Whether the current retrieval budget is sufficient. |
| Mean reciprocal rank | Reciprocal of the rank of the first expected evidence block, averaged across retrieval cases. | Whether correct evidence is near the top, not merely present. |
| Citation support rate | Expected answer content matches and cited blocks cover all expected source fragments on the correct page. | Whether the answer remains tied to source evidence. |
| Abstention accuracy | Unsupported cases return the fixed unavailable answer; unrelated cases return fixed scope guidance. | Whether the system avoids inventing facts. |
| Direct-path accuracy | Direct cases return the expected field and citation without invoking retrieval. | Whether deterministic structured answers stay correct and efficient. |

## Local evaluation workflow

The reviewed dataset is available at `evaluation/fictional_licence_gold_v0.json`. Its ten items were uploaded to `licenceiq/fictional-gold-v0` and read back successfully on 2026-09-20.

Validate the reviewed dataset without contacting the application, an AI provider, or Langfuse:

```powershell
cd backend
uv run python scripts/fictional_gold_eval.py --validate-gold
```

The implemented test-only adapter:

1. Validates and uploads the hash-pinned fictional samples to temporary filesystem storage.
2. Reads and extracts each sample once using real configured providers and application services.
3. Submits each question and permitted prior-question history without expected answers.
4. Captures the actual returned answer, citations, selected evidence and direct lookup usage.
5. Scores all cases locally and publishes linked experiment items and scores to Langfuse.

Run from `backend`:

```powershell
uv run python -m scripts.run_fictional_gold_experiment
uv run python -m scripts.run_fictional_gold_experiment --run
```

The first command is a network-free dry run. `--run` performs paid model calls and publishes the fictional experiment. Refresh the dataset's **Experiments** tab and open the URL printed by the runner. Full local reports are saved under ignored `.runtime/evaluations/`.

The production Q&A response will not expose retrieval scores or vectors. The evaluation seam remains separate from normal user behavior.

## Evaluation boundaries

Evaluator `fictional-gold-v0.2` handles equivalent numeric date formats and multi-line source coverage. Recall and MRR average only the four retrieval cases; citation support uses eight answerable cases, abstention uses two cases, and direct-path accuracy uses four cases. Provider errors count as failures rather than disappearing from the denominator.

These are deterministic reference checks, not an LLM judge, a full hallucination detector, or production accuracy estimates. This runner tests document services with isolated storage; it does not test browser interactions, API authentication, database or MinIO persistence. It exports only the reviewed fictional questions, actual fictional responses and source evidence. The normal application's tracing privacy rules remain separate.
