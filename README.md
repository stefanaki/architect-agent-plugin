# Architect Agent

An agent plugin for the daily work of architecture engineers in Greece. It grows module by
module. The first modules are:

- **Regulations.** Find, quote and cite the Greek building regulations and the fire code
  (π.δ. 41/2018) with every amendment from the Government Gazette. It works offline from bundled
  datasets.
- **Rhino.** Inspect, model, edit and verify geometry in an open Rhino 8 model.
- **Setup.** Install the prerequisite, check the regulations and connect Rhino.

## Install

**1. Install uv.** It is the plugin's only prerequisite, and it downloads Python by itself.

- **Windows:** open PowerShell and run `winget install --id=astral-sh.uv -e`.
- **macOS:** open Terminal and run `curl -LsSf https://astral.sh/uv/install.sh | sh`.

Then **quit the ChatGPT or Codex app completely and open it again**. An app that was running
during the install does not see uv.

**2. Add the plugin:**

```sh
codex plugin marketplace add stefanaki/architect-agent-plugin --ref main
codex plugin add architect-agent@architect-engineers
```

**3. Run the setup.** Start a new chat and ask the agent to set up Architect Agent. The setup:

- checks uv;
- runs the regulations once (the first run downloads Python, about 30 MB);
- if you use Rhino 8, installs the Rhino package and checks the connection.

Rhino must be running for the agent to work with a model.

## Update

```sh
codex plugin marketplace upgrade architect-engineers
```

Start a new chat afterwards. If the Rhino package changed, run the setup again and restart
Rhino.

## Privacy

- **The plugin keeps no profile** and sends nothing anywhere.
- **Your work stays in your project folder.** Notes and exports go there, never into the plugin.

## Limits

- **The regulations are Gazette texts, not a consolidation.** The agent applies the amendments
  itself and says how far the Gazette was checked. This is not legal advice: check the
  official text for decisions with legal or financial consequences.
- **The Rhino connection is local** and needs a local agent session.

## Development

```
.agents/plugins/marketplace.json   marketplace entry
plugins/architect-agent/           the plugin, and the only folder that ships
  plugin.json, mcp.json            manifests
  skills/<name>/                   one self-contained folder per module
tools/gazette/                     builds the regulations data (README inside)
tools/rhino/                       rebuilds the Rhino package (README inside)
tests/                             pytest
```

```sh
uv sync
uv run pytest
uv run ruff check tools tests plugins
```

### Adding a module

1. Add a folder under `plugins/architect-agent/skills/` with a `SKILL.md`, plus any
   `scripts/`, `references/` and `assets/` it needs.
2. Keep scripts to the Python standard library, run with `uv run --no-project`.
3. Use an MCP server only for a live connection to an application, and declare it in
   `mcp.json`.

`AGENTS.md` has the rules for agents that work on this repository.

### Release

1. Bump `version` in `plugins/architect-agent/plugin.json`.
2. Run the tests.
3. Push to `main`. Every push to `main` is a release.

## Licence

- **Code:** MIT (`LICENSE`).
- **The Rhino package:** based on rhinomcp, MIT, by Jingcheng Chen. Its licence ships with it.
- **Legislative texts:** Greek legislative texts are not protected by copyright (law
  2121/1993, article 2(5)).
