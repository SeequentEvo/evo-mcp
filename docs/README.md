# Evo MCP docs

Design documentation for the `evo-mcp` server.

## Scope

These docs cover the **estimation workflow** additions introduced in the `kriging-workflows` branch:
the session/staging infrastructure, MCP tool groups for staging and compute, the skills layer, and the eval harness.

**Not yet covered here:** data ingestion tools (`build_and_create_*`), workspace/file management tools, user administration tools, the broader MCP server setup and configuration.

---

## Contents

### Overview

| File | Description |
|---|---|
| [estimation-workflow-design.md](estimation-workflow-design.md) | End-to-end design: how skills, tools, session, staging, and Evo connect |

### `architecture/`
Deep-dives into each layer of the session-staging stack.

| File | Description |
|---|---|
| [session-layer.md](architecture/session-layer.md) | ObjectRegistry — name → stage_id resolution |
| [staging-layer.md](architecture/staging-layer.md) | StagingService and the plugin object type system |
| [interaction-pattern.md](architecture/interaction-pattern.md) | Two-tool discover/invoke pattern |
| [object-lifecycle.md](architecture/object-lifecycle.md) | How objects are created, used, and published |

### `tools/`
MCP tool groups.

| File | Description |
|---|---|
| [compute-tools.md](tools/compute-tools.md) | Kriging build + run tools |
| [dev-tools.md](tools/dev-tools.md) | Dev/eval tools (fixture seeding, reset) — enabled with `MCP_TOOL_FILTER=dev` |

### `skills/`
LLM skill guides and the eval harness.

| File | Description |
|---|---|
| [skills.md](skills/skills.md) | Skill inventory, orchestrator/sub-skill model, composition diagrams |
| [evals.md](skills/evals.md) | Eval harness, fixture modes, per-skill coverage |

