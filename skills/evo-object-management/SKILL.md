---
name: evo-object-management
description: Imports geoscience objects from Evo into the local session and publishes local objects back to Evo.
---

# Object Management

This skill manages the **Evo boundary** — importing objects from Evo into the local session and publishing local objects back to Evo.

## Tools

- `import_object` — imports any supported Evo object into the session (type auto-detected)
- `publish_object` — publishes a staged session object back to Evo (type auto-detected from payload)

## Trigger Conditions

Use this skill when the user needs to:

- import a geoscience object from Evo into the session
- publish a local object to Evo (create or new version)

## Workflow

1. Confirm `workspace_id` and object role.
2. Locate object identifiers if needed (by name or search).
3. Call `import_object` with the object's UUID, or `publish_object` with the object's session name.

## Notes

- Subblocked block models can be imported but not published. (Not yet supported by SDK.)
- Only regular block models can be published to Evo.

## Error Handling

- Invalid workspace or object IDs: fail with explicit resolution message.
- Object role mismatch: fail with expected type in message.

## Required Inputs

- `workspace_id`
- Object name or object ID for the item to import or publish

## Optional Inputs

- `object_path` (for publish operations)
- `mode` (`create` or `new_version` for publish operations)
