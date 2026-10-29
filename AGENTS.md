# AGENTS.md

An agent plugin for the daily work of architecture engineers in Greece. It grows one module at
a time, and each module is a skill. `README.md` has the overview.

## Layout

- **Only `plugins/architect-agent/` ships to engineers.** `tools/`, `tests/` and `notes/`
  (git-ignored) never ship.
- **Each module is a self-contained skill** in `plugins/architect-agent/skills/<name>/`: a
  `SKILL.md`, plus its `scripts/`, `references/` and `assets/`.
- **The agent that runs the plugin reads only the `SKILL.md` files**, and what they point to.
  Put guidance for that agent there, not here.

## Commands

```sh
uv sync                                   # dev environment
uv run pytest                             # all tests, against the bundled data
uv run ruff check tools tests plugins
uv run tools/gazette/cli.py <command>     # the regulations build
```

## Rules

- **Never edit `skills/regulations/data/` by hand.** Change `tools/gazette/` and rebuild it.
  Read `tools/gazette/README.md` first.
- **The id grammar lives in `skills/regulations/scripts/ids.py`.** The query script and the
  harness both use it, and changing it changes every citation.
- **Plugin scripts use the Python standard library only.** They run as
  `uv run --no-project <script>` on Windows, macOS and Linux. Write UTF-8 to stdout, and never
  assume a POSIX shell in skill instructions.
- **All docs, manifests and skill instructions are in English.** The agent answers engineers
  in Greek, and quotes legal text in the original Greek.
- **MCP only for live connections to applications** (Rhino). Use skills and scripts for
  everything else.
- **Before changing the Rhino package or its `mcp.json` pin**, read `tools/rhino/README.md`.
- **A push to `main` is a release.** Bump `version` in `plugins/architect-agent/plugin.json`
  with every change to the plugin.
