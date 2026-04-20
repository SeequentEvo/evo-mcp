---
name: mcp-skill-eval
description: Runs and evaluates evo-mcp skill evals against a workspace — tests, benchmarks, and assesses skill behaviour.
---

# MCP Skill Eval

Run multi-skill evals with one shared seeded workspace, one executor subagent per skill, then grade and aggregate the results.

## Hard rules

- Run setup exactly once per iteration: `mcp_evo-mcp_staging_reset()` then `mcp_evo-mcp_staging_seed(...)`.
- Spawn one executor subagent per skill, not per eval.
- Spawn all skill subagents in the same turn unless user asks for serial execution.
- Fixtures must be unique per skill test suite. If fixture keys/object names overlap across skills, stop and fix before seeding.
- Fail fast per eval: stop that specific eval attempt immediately when it fails.
- Eval independence is mandatory: a failed eval must not stop remaining evals in the same skill.
- Do not retry or reattempt a failed eval in the same iteration.
- Always write iteration summary artifacts: `summary.json` and `recommendations.md`.

## Fast checklist

1. Select target skills and load each `skill-evals/<skill-name>/evals.json`.
2. Build `fixture_files` from selected skills where `skill-evals/<skill-name>/fixtures.json` exists.
3. Reset and seed once; capture `workspace_id`.
4. Spawn one executor subagent per skill.
5. Draft assertions while executors run; write `eval_metadata.json` per eval.
6. Capture `total_tokens` and `duration_ms` into skill-level `timing.json` when each executor completes.
7. Grade each eval output into `grading.json`.
8. Aggregate into iteration-level `summary.json` and `recommendations.md`.

Do not advance until required files for the current step exist.

## Step details

### 1) Select scope

- If user says "all", select directories under `skills/` that have `SKILL.md` and have a matching entry under `skill-evals/<skill-name>/evals.json` in this skill.
- If a skill defines preconditions/setup in its docs/eval metadata, run those before spawning its executor.

Done when: final skill list is locked and all eval prompts are loaded.

### 2) Shared setup (once)

- Build `fixture_files` dynamically from selected skills.
- Include optional user-provided fixture files.
- De-duplicate list.
- Run:

```
mcp_evo-mcp_staging_reset()
mcp_evo-mcp_staging_seed(fixture_files=[...])
```

- Capture `workspace_id` from seed result.
- Some skills may not have fixtures; continue with those that do.

Done when: shared workspace is seeded once and `workspace_id` is recorded.

### 3) Execute (one subagent per skill)

- Spawn exactly one executor subagent for each selected skill.
- Executor must run all evals in that skill's `skill-evals/<skill-name>/evals.json`.
- Evals run serially inside each skill executor unless the skill requires otherwise.
- If an eval fails, mark it failed
- Do not retry any failed eval in the same run.
- Do not stop the entire skill run on a single eval failure unless the user explicitly requests `halt_on_first_error=true`.
- Use prompt template in `references/templates.md`.

Done when: each selected skill has exactly one active or completed executor subagent.

### 4) Prepare assertions while running

- Convert each eval's `expected_output` into binary pass/fail assertions.
- Write `eval_metadata.json` per eval.
- Keep assertions concrete and verifiable.

Done when: each eval has assertion metadata.

### 5) Capture timing

- On each executor completion notification, write skill-level `timing.json` with `total_tokens`, `duration_ms`, and `total_duration_seconds`.
- If per-eval timing exists, store it under each eval directory too.

Done when: every selected skill has `timing.json`.

### 6) Grade

- Grade each eval output against `eval_metadata.json`.
- Write `grading.json` per eval.
- `expectations` entries must use fields `text`, `passed`, `evidence`.
- Copy `execution_metrics` from eval-level `outputs/metrics.json`.

Done when: every executed eval has `grading.json`.

### 7) Aggregate and recommend

- Write iteration-level `summary.json` and `recommendations.md`.
- Recommendations must be prioritized and actionable, with issue, impact, exact fix, file location, and verification step.

Done when: both files exist and cover all evaluated skills.

## Workspace layout

```
skills-eval-workspace/
└── iteration-N/
    ├── summary.json
    ├── recommendations.md
    ├── <skill-name>/
    │   ├── timing.json
    │   ├── outputs/
    │   │   └── metrics.json
    │   ├── eval-<id>/
    │   │   ├── outputs/
    │   │   │   └── metrics.json
    │   │   ├── eval_metadata.json
    │   │   └── grading.json
    │   └── ...
    └── ...
```

Keep prior iterations (`iteration-1`, `iteration-2`, ...). Do not delete old runs.

## Re-runs and subsets

- Subset run: setup once, then spawn one executor for each selected skill.
- Re-run after skill edits: use a new `iteration-N` directory.
- Reuse seeded workspace only if fixture inputs did not change.
- If fixtures changed, repeat Shared setup.

## Required Inputs

- One or more skill names (or "all" to select every skill with evals)
- Each target skill must have `skill-evals/<skill-name>/evals.json`

## Optional Inputs

- Additional fixture files beyond skill-bundled fixtures
- Iteration number override (defaults to next sequential)
- Serial execution flag (default is parallel)

## Error Handling

- **Missing evals.json for a selected skill**: Skip that skill with a warning rather than aborting the entire run.
- **Seed failure**: Report the seed error and do not proceed to execution. Common causes: malformed fixture JSON, unsupported object types, or connectivity issues.
- **Executor subagent failure**: Capture partial output and continue with remaining skills. Report which skill failed and at which eval.
- **Eval failure inside executor**: Stop only the failing eval attempt, mark that eval as failed, and continue with the remaining evals.
- **Grading mismatch**: If grading.json cannot be written (e.g., missing outputs), mark the eval as "ungraded" with an explanation.

## Reference files

- `references/templates.md` for executor prompt template and recommendation template.
- `references/schemas.md` for JSON structures (`metrics.json`, `timing.json`, `eval_metadata.json`, `grading.json`, `summary.json`).
