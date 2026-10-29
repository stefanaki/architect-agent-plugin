---
name: setup
description: Set up, check or repair Architect Agent on this computer. Installs uv (the plugin's only prerequisite), checks the regulations and connects Rhino. Use on first use, after an update, or when a plugin tool fails.
---

# Setup

Talk to the engineer in Greek. They are not expected to know the terminal: run every
command yourself and explain each step in one plain sentence. The plugin root is two
directories above this file. Never write files into it. Quote paths in commands,
because they can contain spaces.

## 1. uv

Run `uv --version`. If it works, go to step 2.

If it fails, install uv:

- **Windows:** `winget install --id=astral-sh.uv -e`. If winget is missing, run
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
- **macOS:** `curl -LsSf https://astral.sh/uv/install.sh | sh`.

The installer adds uv to PATH, but an app that is already running does not see the
change. Ask the engineer to quit this app completely, open it again, and ask for setup
again. Stop here until they do. If `uv --version` still fails after the restart, report
the installer's output. Do not try other installers.

## 2. Regulations

Run:

```
uv run --no-project "<plugin-root>/skills/regulations/scripts/regs.py" info
```

The first run downloads Python, about 30 MB, so tell the engineer it can take a minute.

Check that the Greek text in the output is readable. If it is garbled (for example
`Î`, `Ã`, or `?` instead of Greek letters), run the same command once more on Windows,
prefixed with
`[Console]::OutputEncoding = [Text.Encoding]::UTF8;`. If that fixes it, the regulations
skill uses the same prefix. Report the result either way.

## 3. Rhino (only if the engineer uses Rhino 8)

Ask whether they use Rhino 8. If they don't, skip this step.

Find Yak, Rhino's package manager:

- **Windows:** `C:\Program Files\Rhino 8\System\Yak.exe`
- **macOS:** `/Applications/Rhino 8.app/Contents/Resources/bin/yak`

If it is not there, ask where Rhino is installed. Run `<yak> list`:

- If `rhinomcp-autostart` is listed with the version of the bundled package, it is already
  installed.
- If upstream `rhinomcp` is listed, uninstall it with `<yak> uninstall rhinomcp`. It
  conflicts with the bundled package.
- Otherwise, install the bundled package: `<yak> install "<plugin-root>/skills/rhino/assets/<file>.yak"`.
  Use the one `rhinomcp-autostart-*.yak` file in that folder.

Ask the engineer to restart Rhino and open any model. Then call a harmless Rhino MCP tool
that reads the document, such as the document info tool.

- **It answers:** Rhino is connected.
- **No-connection error:** Rhino is closed, or still needs a restart.
- **No Rhino tools at all:** the plugin is not enabled, or the app needs a restart.

## Report

Tell the engineer, in Greek and briefly:

- whether uv works;
- whether the regulations work;
- whether Rhino is connected or skipped;
- anything they still have to do, such as restarting an app.

Say setup is complete only when every step that applies has succeeded.
