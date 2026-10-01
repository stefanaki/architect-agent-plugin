# Revit adapter

Vendors [Demolinator/revit-mcp-server](https://github.com/Demolinator/revit-mcp-server)
at commit `40af5a7860b4470ad8f80ea327cf4a9cd31ca0a6` for Revit 2024–2027 on Windows.
The upstream files and MIT license live in `revit-mcp.extension/`.

The plugin starts the bundled Python MCP server using Python 3.13 and its pinned
`requirements.txt`. Setup copies the pyRevit extension to
`~/.architect-agent/cad/revit/revit-mcp.extension/`, so plugin updates cannot
remove the extension loaded by the CAD app.

## Setup

1. Check `pyrevit env`. If missing, install the signed installer from
   https://github.com/pyrevitlabs/pyRevit/releases/latest.
2. Close Revit before staging an extension update. Run:

   ```sh
   uv run --no-project "<plugin-root>/scripts/engineer.py" stage-revit
   ```

   Use an absolute plugin path. Staging copies the bundled source and preserves
   the previous extension in a backup folder.
3. Register the printed parent directory using
   `pyrevit extensions paths add "<parent>"`; verify with
   `pyrevit extensions paths`. In pyRevit Settings > Routes, enable Routes Server,
   save, and restart Revit. Do not install the original upstream extension from
   pyRevit's extension manager; it is a different implementation.
4. Reconnect the plugin after setup. Verify with a harmless model inspection.
   A listening port alone does not prove tool calls work.

Run setup again after an adapter update to keep the server and in-app extension
on the same version. Live Windows/Revit installation remains unverified until
exercised on that machine.

## Maintain

Replace the vendored files with a tested upstream revision and update the commit
record above. Commit the files directly; no submodule or adapter download step
is required for marketplace installation.

## CAD workflow

Before any change, call `get_revit_model_info` and `get_current_view_info`.
Read affected elements with `get_element_properties`. Prefer named tools to
`execute_revit_code`; the latter runs IronPython 2.7 inside Revit. Element ids
are 64-bit in Revit 2024 and later. Changes run in undoable transactions; verify
the result and report exactly what changed and the affected element ids.

Revit is Windows only. Routes listens on `127.0.0.1:48884`. If status fails,
Revit is closed, needs restarting, or Routes is disabled. A 404 under
`/revit_mcp/status/` means pyRevit did not load the extension. Use setup to check
the extension registration. Do not claim a live connection on macOS.
