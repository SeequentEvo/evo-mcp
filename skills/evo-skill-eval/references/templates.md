# Templates

## Executor subagent prompt

Use one executor subagent per skill.

```text
Execute all eval tasks for skill: <skill-name>

Inputs:
- Skill path: skills/<skill-name>/SKILL.md
- Evals file: skills/<skill-name>/evals/evals.json
- Workspace ID: <workspace_id>

Context:
- Shared setup is already complete.
- Do NOT call mcp_evo-mcp_reset_staging or mcp_evo-mcp_seed.

Execution requirements:
- Run every eval entry in evals.json.
- Run evals serially unless skill instructions require another order.
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
