# Skills — `skills/`

Skills are **Markdown guides** that tell an LLM how to use MCP tools to complete
end-to-end workflows. They encode domain knowledge and workflow logic separately
from the tools themselves.

---

## What a Skill Is

```
skills/<skill-name>/
  SKILL.md          ← LLM instruction guide (frontmatter: name, description)
  references/       ← supplementary detail loaded on-demand
    payload_contract.md
    tool_call_reference.md
    ...
```

The `description` frontmatter field is used by the LLM to decide **when to invoke**
the skill. Skills are loaded via FastMCP's `SkillsDirectoryProvider`.

---

## Two Kinds of Skill

```mermaid
flowchart LR
    subgraph ORCH["Orchestrator Skill"]
        direction TB
        O1["Defines the end-to-end workflow\nphases and decision points"]
        O2["Knows which sub-skill handles\neach phase"]
        O3["Passes object names between\nphases as the shared context"]
        O1 --- O2 --- O3
    end

    subgraph SUB["Sub-skill  (specialised)"]
        direction TB
        S1["Owns a single concern\ne.g. create object, validate, execute"]
        S2["Provides domain defaults\ne.g. typical ranges, recommended params"]
        S3["Provides code snippets /\npayload examples for tool calls"]
        S4["Calls MCP tools directly"]
        S1 --- S2 --- S3 --- S4
    end

    ORCH -->|"delegates phase\nwith context"| SUB
```

---

## How an Orchestrator Delegates

```mermaid
flowchart TD
    USER(["User request"])
    USER --> ORCH

    ORCH["Orchestrator skill\nreads user intent,\nselects next phase"]

    ORCH -->|phase A| SA["Sub-skill A\ne.g. discover objects"]
    ORCH -->|phase B| SB["Sub-skill B\ne.g. configure model"]
    ORCH -->|phase C| SC["Sub-skill C\ne.g. validate + execute"]

    SA --> TA["MCP tool(s)"]
    SB --> TB["MCP tool(s)"]
    SC --> TC["MCP tool(s)"]

    TA & TB & TC -->|"results / object names\npassed back to orchestrator"| ORCH
```

---

## What a Sub-skill Contributes

```mermaid
flowchart LR
    subgraph SKILL["Sub-skill (SKILL.md)"]
        direction TB
        WH["When to invoke\ndescription triggers automatic selection"]
        DEF["Domain defaults\ntypical parameter values, sensible ranges"]
        SNAP["Code snippets\nexact tool call shape with example values"]
        ERR["Error handling\nwhat to check, how to recover"]
        WH --- DEF --- SNAP --- ERR
    end

    SKILL -->|"instructs LLM to call"| TOOL["MCP Tool"]
    TOOL -->|"result"| SKILL
    SKILL -->|"named object / summary\nback to orchestrator"| ORCH["Orchestrator"]
```

---

## Skill Inventory

| Skill | Type | Role |
|---|---|---|
| `kriging-workflow` | **Orchestrator** | End-to-end workflow: data → results |
| `evo-object-discovery` | Sub-skill | Find objects in Evo by name/type |
| `staging-workflow` | Sub-skill | Import, inspect, update, publish staged objects |
| `manage-variogram` | Sub-skill | Create and inspect variograms locally |
| `manage-search-neighborhood` | Sub-skill | Design search neighborhoods |
| `manage-block-model` | Sub-skill | Design block models from extents |
| `manage-point-set` | Sub-skill | Load point sets from CSV |
| `validate-crs` | Sub-skill | Check CRS compatibility between staged objects |
| `evo-kriging-execute` | Sub-skill | Execute kriging with resolved published inputs |
| `kriging-reporting` | Sub-skill | Interpret and summarize kriging results |
| `evo-object-visualisation` | Sub-skill | Generate viewer/portal links |

---

## Syncing Skills to Clients

The `sync_skills` tool copies skills from `skills/` to the platform-specific
skills directory (Copilot, Claude, Cursor, etc.) so chat clients can discover them.

```python
sync_skills(target_platform="copilot", skills=["kriging-workflow", "manage-variogram"])
```
