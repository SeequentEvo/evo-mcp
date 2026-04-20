---
name: staging-workflow
description: Use this skill when the user needs to fetch objects from Evo, inspect or modify staged objects, publish changes back to Evo, or list/remove objects in the session — even if they just say "load my variogram" or "save this to Evo."
---

# Object Staging

Use this skill for object work from start to finish. Translate user intent — fetch, inspect, update, publish, list, remove — into staging operations, keeping mechanics hidden and responses in plain language.

## Trigger Conditions

Use this skill when the user needs to:

- fetch objects from Evo into the session
- inspect object contents or readiness
- apply updates or transformations to a staged object
- check spatial compatibility before compute operations
- publish objects back to Evo
- list what objects are currently staged in the session
- remove or discard a staged object

Do not use this skill when:

- the request does not require session-based object lifecycle operations
- the request is limited to local object design without session management
- the request is limited to pure lookup or visualization without session changes

## Tools

| Tool | Use |
|---|---|
| `staging_import_object` | Fetch an object from Evo into the local session |
| `staging_create_object` | Build a new object locally |
| `staging_list_object_types` | Discover supported object types |
| `staging_list_interactions` | Discover interactions available for an object type |
| `staging_invoke_interaction` | Run an interaction on a staged object |
| `staging_spatial_validation` | Validate CRS compatibility between two staged objects |
| `staging_publish_object` | Publish a staged object to Evo |
| `staging_list` | List all objects currently in the session |
| `staging_discard_object` | Discard/remove/delete an object from the session |

## Workflow

1. Translate the request into object actions.
2. Fetch or create the working object.
3. Inspect and apply requested updates.
4. Run compatibility checks when relevant.
5. Publish when requested.
6. Return a short outcome-focused response.

When the user asks what's in the session, use `staging_list` and present the results as a plain-language table.

Use "Imported from Evo" for objects that have an Evo object ID, and "Local only" for objects that exist only in the session. Do not expose internal envelope fields.
When the user asks to remove or discard an object, use `staging_discard_object` with its name.

## Rules

- Use plain language: fetch, inspect, update, publish, list, remove — not staging terminology.
- Keep tool mechanics in the background; share outcomes, not implementation details.
- Mention technical specifics only when the user asks or when needed to unblock.
- Choose supported actions automatically based on object type.

## Gotchas

- `staging_discard_object` is permanent for the session. Confirm with the user before discarding.
- Publishing an object that was already published creates a new version, not an in-place update.
- `staging_list` only shows objects in the current session — not everything in the Evo workspace.
- An object fetched from Evo and left unchanged already has a valid object ID — do not re-publish it.

## Error Handling

- Explain issues in user terms first.
- Ask only for the minimum missing input.
- Offer the closest supported alternative if a requested action is unavailable.

## Required Inputs

- User intent: fetch, inspect, update, validate, publish, list, or remove
- Enough object context to identify source/target objects

## Optional Inputs

- `workspace_id`
- object identifiers (name, id, optional version)
- publish destination or existing object for version updates
