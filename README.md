# Architect Agent

A modular Codex plugin for architecture engineers, with engineer setup, CAD
adapters and Greek building regulation datasets. Use it in any local project.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Codex with
plugin support, then:

```sh
codex plugin marketplace add stefanaki/architect-agent-plugin --ref main
codex plugin add architect-agent@architect-engineers
```

Start a new local Codex chat and ask "Set up Architect Agent". Setup installs the
selected CAD adapters and checks connections. Supported versions, platforms
and installation requirements are documented in each adapter's
`tools/<adapter>/README.md`. CAD apps must be running for live model access.

Open any project folder in Codex and use the plugin there. Briefs, models, notes
and exports stay in that project; no central project folder or registration is
required. The minimal profile at `~/.architect-agent/profile.json` stores only
preferred name, document credit and CAD apps/versions. Staged adapters live
under `~/.architect-agent/cad/`. Never store profiles or client projects
inside the installed plugin. Local CAD connections require a local Codex session;
they are not hosted web endpoints.

## Update

```sh
codex plugin marketplace upgrade architect-engineers
```

Refresh the installed plugin when prompted and start a new chat. Run setup after
an adapter update, then restart CAD. Profile and project data survive updates.
Git marketplace refresh provides over-the-air delivery; silent background update
behavior depends on the Codex client and workspace policy.

Legal text is Greek; other instructions are English. Regulations are Gazette
texts, not consolidated law. The bundled datasets are the record the skill answers
from, offline: it queries them with `scripts/regulations.py` (search, text,
amendment history, Code/NOK links) and states in each answer how far the Gazette
was checked. The skill never modifies the datasets during an engineer's task.

The manifests, three skills (setup, CAD and regulations), adapters and datasets
are under `plugins/architect-agent/`. Installation and updates use the Git
marketplace on `main`. This marketplace is independent of OpenAI's reviewed public
plugin directory. Upstream license notices accompany bundled adapters;
legislative-text provenance is in the dataset READMEs.

Adapter source or packages and documentation are included. Gazette tooling is
for maintainers working in a source checkout; engineers treat installed datasets
as read-only. Downloaded Gazette PDFs and build caches are regenerated as needed
and are not distributed.

## Maintain

Edit the plugin under `plugins/architect-agent/`. Keep
`.agents/plugins/marketplace.json` pointing to that directory. For an update,
bump the version in `plugins/architect-agent/plugin.json`, verify the changes,
and commit and push to `main`. Users receive the changes by refreshing the Git
marketplace as described above. No ZIP packaging, release tags or GitHub Release
workflow is required.

Keep general skills independent of individual CAD apps. Each adapter lives under
`tools/<adapter>/`, with its installation, model workflow, connection details and
limitations in its README. Keep required adapter source or packages bundled
with the plugin and add server configuration to `mcp.json` when needed. The setup
and CAD skills select the relevant adapter documentation.

Update regulations using the Gazette CLI from `plugins/architect-agent/regulations/`:

```sh
python3 gazette/cli.py discover 2012 2026
python3 gazette/cli.py build all
```

Use the current year as the discovery end year. Then run the query tests
(`python3 -m unittest discover -s plugins/architect-agent/tests`) and commit the
generated data, including `regulations/index.json`, after the build checks pass. No separate coverage snapshot or checksum file needs updating.
