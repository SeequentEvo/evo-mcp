---
name: evo-skill-eval
description: Run evaluations for one or more evo-mcp skills against a shared workspace. Use this skill whenever someone wants to test, evaluate, benchmark, or grade skill behaviour — especially when running multiple skills simultaneously. Triggers on phrases like "run the evals", "evaluate the skills", "test skill X", "run all skill evals", "check the evals for", or "benchmark skill performance".
---

# Evo Skill Eval

Run multi-skill evals with one shared seeded workspace, one executor subagent per skill, then grade and aggregate the results.

## Hard rules

- Run setup exactly once per iteration: `mcp_evo-mcp_reset_staging()` then `mcp_evo-mcp_seed(...)`.
- Spawn one executor subagent per skill, not per eval.
- Spawn all skill subagents in the same turn unless user asks for serial execution.
- Fixtures must be unique per skill test suite. If fixture keys/object names overlap across skills, stop and fix before seeding.
- Always write iteration summary artifacts: `summary.json` and `recommendations.md`.

## Fast checklist

1. Select target skills and load each `evals/evals.json`.
2. Build `fixture_files` from selected skills where `evals/fixtures.json` exists.
3. Reset and seed once; capture `workspace_id`.
4. Spawn one executor subagent per skill.
5. Draft assertions while executors run; write `eval_metadata.json` per eval.
6. Capture `total_tokens` and `duration_ms` into skill-level `timing.json` when each executor completes.
7. Grade each eval output into `grading.json`.
8. Aggregate into iteration-level `summary.json` and `recommendations.md`.

Do not advance until required files for the current step exist.

## Step details

### 1) Select scope

- If user says "all", select directories under `skills/` that have both `SKILL.md` and `evals/evals.json`.
- If a skill defines preconditions/setup in its docs/eval metadata, run those before spawning its executor.

Done when: final skill list is locked and all eval prompts are loaded.

### 2) Shared setup (once)

- Build `fixture_files` dynamically from selected skills.
- Include optional user-provided fixture files.
- De-duplicate list.
- Run:

```
mcp_evo-mcp_reset_staging()
mcp_evo-mcp_seed(fixture_files=[...])
```

- Capture `workspace_id` from seed result.
- Some skills may not have fixtures; continue with those that do.

Done when: shared workspace is seeded once and `workspace_id` is recorded.

### 3) Execute (one subagent per skill)

- Spawn exactly one executor subagent for each selected skill.
- Executor must run all evals in that skill's `evals/evals.json`.
- Evals run serially inside each skill executor unless the skill requires otherwise.
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

## Reference files

- `references/templates.md` for executor prompt template and recommendation template.
- `references/schemas.md` for JSON structures (`metrics.json`, `timing.json`, `eval_metadata.json`, `grading.json`, `summary.json`).
