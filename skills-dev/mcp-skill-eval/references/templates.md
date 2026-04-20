# Templates

## Executor subagent prompt

Use one executor subagent per skill.

```text
Execute all eval tasks for skill: <skill-name>

Inputs:
- Skill path: skills/<skill-name>/SKILL.md
- Evals file: skills-dev/mcp-skill-eval/skill-evals/<skill-name>/evals.json
- Workspace ID: <workspace_id>

Context:
- Shared setup is already complete.
- Do NOT call mcp_evo-mcp_staging_reset or mcp_evo-mcp_staging_seed.

Execution requirements:
- Run every eval entry in evals.json.
- Run evals serially unless skill instructions require another order.
- Treat each eval as independent: never terminate the whole skill run because one eval fails.
- Do not retry or reattempt a failed eval in the same iteration.
- Save per-eval artifacts to:
  skills-eval-workspace/iteration-N/<skill-name>/eval-<id>/outputs/
- Write per-eval metrics.json in each eval outputs directory.
- Write aggregated skill metrics to:
  skills-eval-workspace/iteration-N/<skill-name>/outputs/metrics.json
```

## Recommendation entry template

Use this format for each recommendation in recommendations.md:

```markdown
### Priority <1|2|3> - <short title>

- Issue pattern: <failure pattern>
- Impact: <why it matters>
- Exact change: <specific update to make>
- Location: <skill path / eval file / fixture file>
- Verification: <how to confirm in next iteration>
```
