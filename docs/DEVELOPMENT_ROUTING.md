# Coding model routing for LicenceIQ

Adopted on 19 September 2026 at the user's request. The root [AGENTS.md](../AGENTS.md) makes the installed `coding-orchestrator` skill part of development across phases. This is a project workflow for coding assistants; it does not add a model router to the LicenceIQ application.

## Default routes

| Tier | Score | Preferred worker model | Reasoning effort | Typical bounded work |
| --- | --- | --- | --- | --- |
| Fast | 0-2 | `gpt-5.6-luna` | low | Clear copy changes, documentation updates, isolated mechanical edits |
| Balanced | 3-5 | `gpt-5.6-terra` | medium | Frontend features using an agreed API, ordinary form behavior, focused tests |
| Strong | 6-8, or high-impact risk | `gpt-5.6-sol` | high | Difficult state transitions, architecture, evidence integrity, sensitive file access |
| Strong escalation | Actual reasoning or implementation difficulty | `gpt-6-astra` | high | A bounded retry after diagnosis, subject to the remaining attempt budget |

The skill's map supplies these preferences. All four model/effort pairs are exposed by this session's subagent tool. Recheck availability at each future session; the checked-in [capabilities snapshot](routing/capabilities-2026-09-19.json) is historical evidence, not a permanent guarantee. Explicit user choices take precedence within supported capabilities. Do not infer pricing or measured performance from the tier names.

Worker model and effort can be selected through subagent configuration or explicit dispatch; see [OpenAI's subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents). The current coordinator retains its session model. No global Codex configuration is changed by this project setup.

## Assessment and execution

Score each dimension using observed facts:

| Dimension | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Uncertainty | Requirements and cause established | Some investigation or assumptions | Ambiguous requirements or conflicting evidence |
| Scope | One isolated behavior | Connected components | Cross-service behavior or architecture |
| Reasoning | Mechanical change | Several interacting conditions | Algorithms, concurrency, or complex state/lifecycle reasoning |
| Verification | Reliable existing check | Multiple checks or focused new coverage | Difficult reproduction or weak coverage |

Add the four scores. Apply the high-risk minimum when the actual change can cross a security boundary or damage data integrity; a document merely discussing security does not trigger the override. Keep an explicit reason for the risk rating.

1. Inspect the authorized work and agree shared contracts before splitting implementation.
2. Run the skill's dependency-free routing helper for explicit routing requests, uncertain choices, and escalations. Check its recommendation against the current host's capabilities.
3. Delegate only useful independent work, with up to two simultaneous workers and separate file ownership. The coordinator continues integration planning, another independent implementation, or verification. Small isolated work can remain with the coordinator; disclose that this is direct execution rather than claiming a worker ran.
4. Record actual dispatch separately from the recommendation, with model, effort, scope, owned files, attempt count, acceptance checks, and outcome. A worker handoff must prohibit nested delegation by default.
5. Review changes and validate the resulting behavior. Track up to three total implementation attempts, including the initial attempt, and one model escalation per work unit. Preserve the last actual route across retries. Diagnose missing dependencies, unavailable credentials, and network failures without automatically escalating models.
6. Close the authorized phase with its evidence and limitations. Begin the next phase only when the user requests it.

These limits are workflow guidance, not hard billing or token controls. If required tools or supported models are unavailable, report the limitation and apply the skill's supported fallback rules without pretending that a dispatch occurred.

## Applying the rules to this application

| Work unit | Initial routing expectation | What determines the final route |
| --- | --- | --- |
| Documentation or small visual adjustment | Fast; often direct coordinator execution | Clear scope and reliable review |
| Upload widget, preview, and API client | Balanced | Agreed backend contract; request, error, and preview cleanup states |
| Upload validation and private storage | Strong minimum | Untrusted files, size enforcement, safe paths, private access, cleanup |
| OCR adapter | Balanced or strong | Provider contract, page handling, fallback rules, and failure recovery |
| Structured extraction and citations | Strong when reasoning spans extraction, normalization, and evidence validation | Prevent unsupported values and retain links to actual page evidence |
| Review form | Balanced for UI; strong for changes that threaten saved evidence or data integrity | Keep original values and user corrections distinguishable |
| Document Q&A | Strong for retrieval isolation and grounding | Restrict evidence to the selected document and handle missing information |
| Packaging and demo documentation | Fast or balanced | Existing verified setup versus unresolved deployment behavior |

These are starting expectations, not pre-authorized implementation or permanent phase-wide scores. Reassess smaller work units against current code when each phase begins. App OCR/LLM provider selection remains separate from the models used to build the app.

## Initial verification record

[Initial assessments](routing/initial-assessments.json) contain three cases: this workflow setup, a proposed frontend upload work unit, and a proposed backend upload work unit. The future upload assessments are provisional and have not been implemented or dispatched.

The skill helper is run against each assessment's `task` object and the capabilities snapshot. Its output is recorded in [initial recommendations](routing/initial-recommendations.json). This demonstrates the fast route, balanced route, and the strong risk override even at a balanced complexity score. No implementation attempts are charged to unexecuted examples.

Validation on 19 September 2026: all three expected model/effort recommendations matched supported pairs; local documentation links and the helper's attempt, escalation, and worker limits passed verification. This documentation setup was completed directly by the coordinator. No workers were dispatched, no application code changed, and application tests were not rerun for this update.

To use the helper on a future individual task JSON in PowerShell:

```powershell
python C:/Users/aksha/.codex/skills/coding-orchestrator/scripts/select_route.py `
  --task path/to/task-assessment.json `
  --available path/to/current-host-capabilities.json
```

The helper only recommends a route. It does not launch a worker. The coordinator performs and records any actual dispatch using the supported tools.
