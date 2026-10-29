#!/usr/bin/env python3
"""Rebuild the vendored rhinomcp-autostart Yak package from an upstream release.

Maintainer tool; standard library only. Requires git, the .NET SDK and Rhino 8's
Yak (run through Wine on Linux). By default it builds the newest upstream
`releases/*` tag, applies `autostart.patch` plus PICKS, and replaces the
vendored package, the `mcp.json` server pin and the README provenance.

  build.py --check              report the vendored and newest upstream versions
  build.py                      rebuild from the newest release
  build.py --release 0.4.1.1    rebuild from a specific release
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent                  # tools/rhino/
PLUGIN_ROOT = HERE.parents[1] / "plugins" / "architect-agent"
MCP_JSON = PLUGIN_ROOT / "mcp.json"
YAK_DIR = PLUGIN_ROOT / "skills" / "rhino" / "assets"   # The vendored package ships with the rhino skill.
README = HERE / "README.md"
PATCH = HERE / "autostart.patch"

UPSTREAM = "https://github.com/jingcheng-chen/rhinomcp.git"
PACKAGE = "rhinomcp-autostart"
DESCRIPTION_SUFFIX = " (fork that starts the MCP listener with Rhino)"
YAK_PATTERN = re.compile(r"rhinomcp-autostart-[0-9][\w.]*-rh\d+_\d+-any\.yak")

# Upstream commits applied on top of the release. Each is skipped once the
# release already contains it, so the list only needs pruning, never editing.
PICKS = [
    ("11bc4fb7ceecff1dc94ff1b80c435a5fe0b3fc1e", "Fix per-connection handler thread leak"),
]


def run(*args, cwd=None, capture=False, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def git(src, *args, capture=False):
    return run("git", "-C", str(src), *args, capture=capture)


def version_key(text):
    return tuple(int(part) for part in text.split("."))


def vendored_version():
    match = re.search(r'"rhinomcp==([^"]+)"', MCP_JSON.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def latest_release(src):
    tags = git(src, "tag", "--list", "releases/*", capture=True).split()
    versions = [tag.removeprefix("releases/") for tag in tags]
    versions = [v for v in versions if re.fullmatch(r"\d+(\.\d+)*", v)]
    if not versions:
        raise SystemExit("No releases/* tags found upstream")
    return max(versions, key=version_key)


def on_pypi(version):
    with urllib.request.urlopen("https://pypi.org/pypi/rhinomcp/json", timeout=30) as response:
        return version in json.load(response)["releases"]


def prepare_clone(src):
    if not (src / ".git").exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", UPSTREAM, str(src))
    git(src, "fetch", "--tags", "--force", "origin")
    if git(src, "status", "--porcelain", "--untracked-files=no", capture=True):
        raise SystemExit(f"{src} has uncommitted changes; commit or discard them first")


def resolve_pick(src, sha):
    try:
        return git(src, "rev-parse", "--verify", f"{sha}^{{commit}}", capture=True)
    except subprocess.CalledProcessError:
        raise SystemExit(f"Upstream commit {sha} not found; prune it from PICKS") from None


def rename_manifest(path):
    text = path.read_text(encoding="utf-8")
    text, names = re.subn(r"(?m)^name:.*$", f"name: {PACKAGE}", text)
    text, descriptions = re.subn(
        r"(?m)^description:\s*['\"]?(.*?)['\"]?\s*$",
        lambda match: f"description: {match.group(1)}{DESCRIPTION_SUFFIX}", text)
    if names != 1 or descriptions != 1:
        raise SystemExit(f"Unexpected layout in {path}; update rename_manifest()")
    path.write_text(text, encoding="utf-8")


def make_fork(src, version):
    tag = f"releases/{version}"
    branch = f"autostart/{version}"
    git(src, "checkout", "--quiet", "-B", branch, tag)
    picked = []
    for sha, title in PICKS:
        full = resolve_pick(src, sha)
        if subprocess.run(["git", "-C", str(src), "merge-base", "--is-ancestor", full, tag]
                          ).returncode == 0:
            print(f"skip {full[:7]} {title}: already in {tag}")
            continue
        git(src, "cherry-pick", "-x", full)
        picked.append((full[:7], title))
    git(src, "apply", str(PATCH))
    rename_manifest(src / "plugin" / "manifest.yml")
    git(src, "commit", "--quiet", "-am", "Autostart: start the MCP listener when Rhino loads")
    return {
        "tag": tag,
        "branch": branch,
        "upstream": git(src, "rev-parse", "--short", tag, capture=True),
        "fork": git(src, "rev-parse", "--short", "HEAD", capture=True),
        "picked": picked,
    }


def yak_command(args):
    if args.yak:
        return [args.yak], None
    system = platform.system()
    if system == "Darwin":
        return ["/Applications/Rhino 8.app/Contents/Resources/bin/yak"], None
    if system == "Windows":
        return [r"C:\Program Files\Rhino 8\System\Yak.exe"], None
    prefix = Path(os.environ.get("WINEPREFIX", "~/.wine-rhino8")).expanduser()
    if not (prefix / "drive_c/Program Files/Rhino 8/System/Yak.exe").exists():
        raise SystemExit(f"Rhino 8 Yak.exe not found in Wine prefix {prefix}; set WINEPREFIX")
    wine = args.wine or shutil.which("wine") or str(Path("~/.local/share/wine-rhino/bin/wine").expanduser())
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG="-all")
    return [wine, r"C:\Program Files\Rhino 8\System\Yak.exe"], env


def build_package(src, args):
    plugin = src / "plugin"
    for stale in ("bin", "obj"):
        shutil.rmtree(plugin / stale, ignore_errors=True)
    run("dotnet", "build", str(plugin / "rhinomcp.csproj"), "--configuration", "Release")
    output = plugin / "bin" / "Release" / "net8.0"
    stage = Path(tempfile.mkdtemp(prefix="rhinomcp-yak-"))
    (stage / "net8.0").mkdir()
    for path in [*output.glob("*.dll"), *output.glob("*.rhp")]:
        shutil.copy2(path, stage / "net8.0")
    shutil.copy2(plugin / "manifest.yml", stage)
    command, env = yak_command(args)
    run(*command, "build", cwd=stage, env=env)
    packages = [path for path in stage.glob("*.yak") if YAK_PATTERN.fullmatch(path.name)]
    if len(packages) != 1:
        raise SystemExit(f"Expected one {PACKAGE} package in {stage}, found {packages}")
    with zipfile.ZipFile(packages[0]) as package:
        if "net8.0/rhinomcp.rhp" not in package.namelist():
            raise SystemExit(f"{packages[0].name} has no net8.0/rhinomcp.rhp")
        if f"name: {PACKAGE}" not in package.read("manifest.yml").decode("utf-8"):
            raise SystemExit(f"{packages[0].name} manifest is not named {PACKAGE}")
    return packages[0]


def provenance(version, fork):
    lines = [
        f"- Upstream: rhinomcp {version}, tag `{fork['tag']}`, commit `{fork['upstream']}`. "
        "The Python server on PyPI is used unchanged.",
    ]
    for sha, title in fork["picked"]:
        lines.append(f"- Added from upstream `main` (not in the release): `{sha}` {title}.")
    lines.append(
        f"- Fork: `tools/rhino/autostart.patch` plus the package rename, commit `{fork['fork']}` "
        f"on branch `{fork['branch']}` of a local upstream clone, built by `tools/rhino/build.py`.")
    return "\n".join(lines)


def vendor(package, version, fork):
    for old in YAK_DIR.glob("rhinomcp-autostart-*.yak"):
        old.unlink()
    shutil.copy2(package, YAK_DIR / package.name)

    mcp = MCP_JSON.read_text(encoding="utf-8")
    MCP_JSON.write_text(re.sub(r'"rhinomcp==[^"]+"', f'"rhinomcp=={version}"', mcp),
                        encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    readme = YAK_PATTERN.sub(package.name, readme)
    readme = re.sub(r"rhinomcp==[0-9][\w.]*", f"rhinomcp=={version}", readme)
    readme, blocks = re.subn(
        r"(<!-- provenance:start -->\n).*?(\n<!-- provenance:end -->)",
        lambda match: match.group(1) + provenance(version, fork) + match.group(2),
        readme, flags=re.S)
    if blocks != 1:
        raise SystemExit(f"{README} lacks the provenance markers")
    README.write_text(readme, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", help="upstream release version (default: newest)")
    parser.add_argument("--src", type=Path, default=Path("~/dev/rhino-mcp/rhinomcp"),
                        help="local upstream clone, created if missing")
    parser.add_argument("--yak", help="Yak executable (default: Rhino 8's, via Wine on Linux)")
    parser.add_argument("--wine", help="Wine binary on Linux")
    parser.add_argument("--check", action="store_true",
                        help="only compare the vendored and newest upstream versions")
    args = parser.parse_args()
    src = args.src.expanduser().resolve()

    prepare_clone(src)
    newest = latest_release(src)
    current = vendored_version()
    if args.check:
        print(f"vendored {current}, newest upstream release {newest}")
        return 0 if current == newest else 1

    version = args.release or newest
    if not git(src, "tag", "--list", f"releases/{version}", capture=True):
        raise SystemExit(f"No upstream tag releases/{version}")
    if not on_pypi(version):
        raise SystemExit(f"rhinomcp {version} is not on PyPI; mcp.json could not pin it")

    fork = make_fork(src, version)
    package = build_package(src, args)
    vendor(package, version, fork)
    shutil.rmtree(package.parent)
    print(f"\nVendored {package.name} (was {current}); mcp.json pins rhinomcp=={version}.")
    print("Reinstall it into Rhino with yak, restart Rhino and run an MCP check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
