---
name: kriging-workflow
description: Use this skill when the user wants to run kriging end to end — from selecting data through execution and reporting — or needs orchestrated help across multiple kriging setup steps. For single-step tasks (just finding objects, just creating a variogram), use the targeted skills instead.
---

# Kriging Workflow

Guide the user through a complete kriging estimation workflow using natural-language conversation. The user describes what they want to estimate, and this orchestrator coordinates the necessary steps behind the scenes.

Users are geologists. They work with object names, attribute names, and geoscience concepts — never with internal identifiers, tool names, or payload structures.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when the user wants to:

- run kriging to estimate grades, properties, or other attributes
- set up a kriging workflow from their existing data
- compare different kriging configurations (method, neighborhood, attributes)
- estimate into a block model or regular grid from sample data

Do not use this skill when:

- the user only needs a single focused task (discovery, CRS check, variogram edit, neighborhood design, or reporting)
- no kriging workflow is being requested
- the user is asking for generic object staging outside a kriging context

## End-to-End Workflow

The orchestrator manages the conversation and assembles resolved inputs across the steps below. Some steps are handled directly by the orchestrator; others are delegated to a named skill.

For all object fetch, inspect, update, and publish behavior, follow the `staging-workflow` skill patterns and keep staging internals hidden from the user.

**What gets assembled:** workspace → staged objects → validated CRS → neighborhood payload → confirmed attribute names → published object IDs → kriging results

---

### Phase 1 — Gather Inputs

#### Step 1: Confirm workspace *(orchestrator)*
Call `list_workspaces` and present the results to the user by name. Ask them to confirm which workspace contains their data. Capture the `workspace_id`.

#### Step 2: Resolve or create objects *(orchestrator + skills)*
Identify the source point set, variogram, and target block model. Each object may follow either path — a mixed combination is valid (e.g., variogram from Evo, block model created locally):

- **Object exists in Evo:**
  1. Find by name → *skill: `evo-object-discovery`*
  2. Import into local session → *skill: `staging-workflow`*
- **Object needs to be created locally:**
  - Source point set from CSV → *skill: `manage-point-set`*
  - New variogram from parameters → *skill: `manage-variogram`*
  - New block model from extents → *skill: `manage-block-model`*

**Assembles:** locally staged objects (sourced from Evo, created locally, or a mix of both)

#### Step 3: Validate spatial compatibility — *skill: `validate-crs`*
Delegate to this skill once all objects are staged.
Do not proceed until validation passes or the user explicitly accepts a mismatch.

#### Step 4: Design the search neighborhood — *skill: `manage-search-neighborhood`*
Delegate to this skill once CRS validation has passed.
**Assembles:** `search` neighborhood payload

#### Step 5: Confirm attribute names *(orchestrator)*
Ask the user which attribute to estimate from (source) and what to call the result on the target.
**Assembles:** `point_set_attribute`, `target_attribute`

#### Step 6: Publish modified or new objects — *skill: `staging-workflow`*
Before running kriging, ensure all required objects have valid workspace object IDs. Only publish objects that need it:

- **New staged objects** (created in steps 2): must be published
- **Objects modified since import** (e.g., variogram re-fitted, block model redesigned): must be re-published
- **Objects fetched from Evo and unchanged**: already have valid object IDs — skip

**Assembles:** `point_set_object_id`, `variogram_object_id`, `target_object_id`

---

### Phase 2 — Execute

#### Step 7: Confirm final parameters *(orchestrator)*
Before running kriging, present a plain-language summary of all assembled inputs and ask the user to confirm:

- Source point set name and attribute
- Variogram name
- Target block model name and result attribute name
- Search neighborhood (ranges, rotation, sample limits)
- Kriging method (ordinary or simple with mean)
- Domain filter, if applicable

Do not proceed to execution until the user explicitly confirms.

#### Step 8: Build and run kriging — *skill: `evo-kriging-execute`*
Delegate to this skill once the user has confirmed all parameters: `workspace_id`, `point_set_object_id`, `point_set_attribute`, `variogram_object_id`, `target_object_id`, `target_attribute`, and `search`.
**Assembles:** structured kriging results with inspection links

---

### Phase 3 — Report and Visualize

#### Step 9: Report results — *skill: `kriging-reporting`*
Delegate to this skill once kriging completes.

#### Step 10 (optional): Visualize — *skill: `evo-object-visualisation`*
Delegate to this skill if the user wants to view the results in the Evo Viewer.


## Conversation Guidelines

- **Ask, don't assume**: confirm object selections, attribute names, and method choices with the user before handing off.
- **Use names, not IDs**: always refer to objects by their name rather than internal identifiers.
- **Speak geoscience**: use terms the user knows — "samples", "estimation target", "search range" — not tool or parameter names.
- **One step at a time**: confirm each step is complete before moving to the next.

## Gotchas

- Mixed object paths are valid (some imported, some locally created); do not force all objects down one path.
- Unchanged imported objects usually do not need re-publish before execution.
- Do not proceed past CRS validation on `mismatch` unless the user explicitly accepts risk.
- Attribute-name confirmation is a required gate before execution, not an optional UX step.
- Final parameter confirmation is mandatory — never delegate to `evo-kriging-execute` without explicit user approval.

## Skill Composition Map

```text
User: "Run kriging on my gold data"
|
+-- 1. Confirm workspace                                        [orchestrator]
+-- 2. Resolve or create objects (per-object, mix allowed)      [orchestrator + skills]
|     +-- evo-object-discovery   -> find in Evo by name
|     +-- staging-workflow       -> import from Evo to session
|     +-- manage-point-set   -> build from CSV
|     +-- manage-variogram   -> create from parameters
|     +-- manage-block-model -> design from extents
+-- 3. validate-crs    -> check CRS                   [skill]
+-- 4. manage-search-neighborhood -> neighborhood payload       [skill]
+-- 5. Confirm attribute names                                  [orchestrator]
+-- 6. staging-workflow          -> publish new/modified only   [skill]
+-- 7. Confirm final parameters  -> user approval gate          [orchestrator]
+-- 8. evo-kriging-execute       -> execute                     [skill]
+-- 9. kriging-reporting         -> summarize                   [skill]
+-- 10. evo-object-visualisation -> view (optional)             [skill]
```

Each skill is self-contained. The orchestrator passes object names between steps — leaf skills resolve names to their internal representations independently.

## Error Handling

- If an object cannot be found, ask the user to try different search terms or confirm the object exists in the workspace.
- If any step fails, explain the issue in plain geoscience language and offer to retry or take an alternative path.
- Never surface raw error codes, stack traces, or internal identifiers to the user.

## Required Inputs

- A workspace to publish objects into and run kriging against
- A source point set (existing in Evo, or built locally from CSV)
- A variogram (existing in Evo, or created locally)
- A target block model or regular grid (existing in Evo, or designed locally)
- Any new or modified objects must be published before kriging runs

## Scope

- Single and multi-scenario runs are both supported.
- Targets may be block models or regular grids.
- Local object creation (point sets, variograms, block models) and Evo import are both supported paths.