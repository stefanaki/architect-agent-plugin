# tools/rhino — building the Rhino package

The plugin connects to Rhino through [rhinomcp](https://github.com/jingcheng-chen/rhinomcp).
rhinomcp has two parts:

- **A Python MCP server.** It comes from PyPI unchanged, and `plugins/architect-agent/mcp.json`
  pins it as `uvx rhinomcp==0.4.1.1`.
- **A Rhino plugin** that listens on `127.0.0.1:1999`.

Upstream's Rhino plugin starts listening only after the user types `mcpstart`. We ship a fork
that starts listening when Rhino starts:
`plugins/architect-agent/skills/rhino/assets/rhinomcp-autostart-0.4.1.1-rh8_17-any.yak`
(Rhino 8 SR17 and later). The `setup` and `rhino` skills install it with Yak.

## Provenance

<!-- provenance:start -->
- Upstream: rhinomcp 0.4.1.1, tag `releases/0.4.1.1`, commit `70b63a2`. The Python server on PyPI is used unchanged.
- Added from upstream `main` (not in the release): `11bc4fb` Fix per-connection handler thread leak.
- Fork: `tools/rhino/autostart.patch` plus the package rename, commit `a705347` on branch `autostart/0.4.1.1` of a local upstream clone, built by `tools/rhino/build.py`.
<!-- provenance:end -->

The fork changes two things:

- **`autostart.patch`.** The plugin loads when Rhino starts and starts the listener.
- **The package name is now `rhinomcp-autostart`.** Rhino's package updates therefore don't
  replace it with upstream.

The plugin GUID stays upstream's, so upstream `rhinomcp` and this package cannot load
together. If both are installed, uninstall upstream. Upstream's MIT licence ships next to the
package.

Tested on macOS and on Linux (Rhino 8 under Wine). Windows uses the same Yak commands but has
not been tested.

## Rebuilding

`build.py` rebuilds the package from an upstream release. It needs git, the .NET SDK (8 or
later) and Rhino 8's Yak. On Linux it runs `Yak.exe` through Wine (`WINEPREFIX`, default
`~/.wine-rhino8`). Upstream is cloned to `~/dev/rhino-mcp/rhinomcp` (change it with `--src`).
Each build gets a local `autostart/<version>` branch there.

```sh
uv run tools/rhino/build.py --check   # exit 1 if outdated
uv run tools/rhino/build.py           # newest release
```

The script:

1. applies the upstream commits in `PICKS` that the release lacks;
2. applies `autostart.patch`;
3. renames the package;
4. builds it;
5. replaces the vendored `.yak`, the `mcp.json` pin and the provenance above.

The package keeps the release's version number, so the server's version check still matches.

If the patch or a pick stops applying, the script stops. Fix the change in the clone and commit
it, then refresh the patch:

```sh
git diff HEAD~1 HEAD -- plugin/RhinoMCPPlugin.cs > tools/rhino/autostart.patch
```
