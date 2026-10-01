---
name: setup
description: Onboard an architecture engineer to Architect Agent in Codex, install or update supported CAD adapters, and check local connections. Use for setup, onboarding, installation, connecting CAD apps, or after plugin updates.
---

# Engineer Setup

Resolve the installed plugin root as two directories above this SKILL.md. Treat
that directory as replaceable, read-only application code. Never write an
engineer's identity, projects, configuration or installed CAD extension there.
All commands below use absolute paths, quoted for spaces.

1. Run `uv --version`. If absent, install uv using its official installer:
   macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`; Windows
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   Verify uv is on the PATH visible to Codex; restart Codex if necessary.
2. Run `uv run --no-project "<plugin-root>/scripts/engineer.py" profile`.
   Ask together for missing information: preferred name, full document credit,
   and CAD apps/versions. Existing profile values are defaults. Keep the profile
   at `~/.architect-agent/profile.json`; save only `name`, `credit`, and `cad`.
   Projects live wherever the engineer opens them in Codex. Do not ask for a
   central data folder or move client files. Codex is the supported agent.
3. Persist answers with `uv run --no-project "<plugin-root>/scripts/engineer.py"
   configure --name "<preferred-name>" --credit "<full-name>"
   --cad "<app/version>"` (repeat `--cad` for each app).
   Never modify the installed plugin or a shared AGENTS.md.
4. Inspect `tools/` for adapters matching the engineer's selected apps. Read
   each matching adapter's README for supported versions/platforms, installation,
   updates and connection requirements, then follow its setup instructions.
   Keep staged adapters under `~/.architect-agent/cad/`, outside the plugin cache.
   An adapter's documentation owns its app-specific commands and limitations.
5. Record unsupported apps and report that no adapter is provided yet.
6. Run `engineer.py doctor`. Then use a harmless MCP
   status/model inspection for selected running CAD apps. A listening port alone
   does not prove that tool calls work. If the plugin tools are missing, verify
   the plugin is enabled and restart Codex. Remove old repo/user MCP registrations
   for the same bridges when migrating, preserving unrelated servers.

The plugin supplies MCP configuration and skills. Do not generate `.mcp.json`,
`.codex/config.toml`, Claude links, or per-project server definitions for engineers.
Do not require the engineer to clone this repository or open the plugin folder.
The report names the saved profile path, installed adapter versions,
verified connections, unsupported apps, and required restarts. Say setup is
complete only after applicable installation steps succeed. A closed CAD app is
a pending live connection, not an installation failure.
