# rhino — the Rhino side of the MCP connection

Codex talks to Rhino through [rhinomcp](https://github.com/jingcheng-chen/rhinomcp):
a Python MCP server (bundled MCP command `uvx rhinomcp==0.4.1`) and a Rhino
plugin that listens on `127.0.0.1:1999`.

Upstream's plugin only listens after you type `mcpstart` in Rhino. The package here is a
fork that listens as soon as Rhino starts, so the agent is connected without any command.

This folder holds the plugin, `rhinomcp-autostart-0.4.1-rh8_17-any.yak`, built for Rhino 8
SR17 and later. The plugin setup skill installs it with `yak`.

## Provenance

- Upstream: rhinomcp 0.4.1, commit `ddc6cfd`. The Python server on PyPI is used unchanged.
- Fork: three files changed on top of upstream (plugin loads at startup and starts the
  listener; package renamed `rhinomcp-autostart` so Rhino's package updates don't replace
  it with upstream). Fork commit `ed79bc2`.
- The fork is a local checkout, not on GitHub yet: `~/dev/rhino-mcp/rhinomcp` on the
  maintainer's Mac. Its `FORK.md` has the build steps (.NET 8 SDK, `dotnet build`, `yak build`).
- The plugin GUID is upstream's. Upstream `rhinomcp` and this package cannot load at once;
  if both are installed, uninstall upstream.
- Tested on macOS. Windows uses the same yak commands and is untested.

## Setup

Paths below are relative to the installed plugin root. Use absolute paths,
quoted for spaces. Run `engineer.py` through `uv run --no-project
"<plugin-root>/scripts/engineer.py"`.

Rhino 8: use the bundled
`tools/rhino/rhinomcp-autostart-0.4.1-rh8_17-any.yak`.
Yak is `/Applications/Rhino 8.app/Contents/Resources/bin/yak` on macOS or
`C:\Program Files\Rhino 8\System\Yak.exe` on Windows. Run `yak list` first;
install the absolute package path only if the expected version is absent.
Upstream `rhinomcp` shares its GUID: uninstall that package if both are present.
Ask for Rhino's location if Yak is missing. Restart Rhino after installation.

## CAD workflow

Before modelling, inspect the open document's units, layers and existing objects.
Use `get_modeling_guidance` for transforms, planar regions and recovery. Verify
geometry against the brief after each meaningful change, including dimensions,
placement and object counts. Successful tool execution does not establish a
correct result. Report changed object ids and exports in the project folder.

Rhino listens on `127.0.0.1:1999` once its adapter loads. A no-connection response
means Rhino is closed or needs restarting after installation. Tell the engineer
to start/restart Rhino. Do not debug Codex for a closed CAD application.
