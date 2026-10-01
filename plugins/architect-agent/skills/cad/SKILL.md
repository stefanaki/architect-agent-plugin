---
name: cad
description: Inspect, model, edit, verify or export architecture geometry using Architect Agent's supported CAD adapters.
---

# CAD Work

Load the engineer profile using the sibling setup skill's `engineer.py profile`
command. Address the engineer by preferred name; credit documents to their full
name when available; ask for document credit if the profile is absent.

Use the current Codex project workspace and its existing conventions. Read its
README and relevant briefs before changing project geometry. If context is
missing, inspect the files and ask for the information needed for the task.
Keep models, notes and exports in that project, preserve existing files, and
never store client material in the installed plugin. No project registration,
central folder or generated README is required.

## Adapter workflow

Resolve the installed plugin root two directories above this file. Inspect
`tools/` and read the selected adapter's README before using its tools. Follow
its model inspection, editing, verification and connection instructions. If the
app or version is unsupported, report that limitation.

Inspect the open model's state before changing geometry, including units,
structure and affected objects. Prefer dedicated tools over arbitrary code.
Verify changes against the brief after each meaningful operation: dimensions,
placement and object counts where applicable. Successful tool execution alone
does not establish a correct result. Report changed object identifiers and
exports in the project folder.

For connection failures, use the adapter's documented checks and the setup skill.
A closed CAD app is a pending live connection; ask the engineer to start or
restart it when required. Do not claim a live connection until a harmless model
inspection succeeds.
