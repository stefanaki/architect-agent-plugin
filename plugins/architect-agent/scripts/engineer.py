#!/usr/bin/env python3
"""Durable engineer state and CAD adapter staging; standard library only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import uuid

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def home_path(value=None):
    return Path(value or "~/.architect-agent").expanduser().resolve()


def validate_home(home):
    if home == PLUGIN_ROOT or PLUGIN_ROOT in home.parents:
        raise ValueError("Engineer data must live outside the installed plugin")


def read_profile(home):
    path = home / "profile.json"
    if not path.exists():
        return {"configured": False}
    saved = json.loads(path.read_text(encoding="utf-8"))
    result = {key: saved[key] for key in ("name", "credit", "cad") if key in saved}
    result["configured"] = True
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(home, name, credit, cad):
    validate_home(home)
    if not name.strip() or not credit.strip() or not all(app.strip() for app in cad):
        raise ValueError("Name, document credit and CAD apps must not be blank")
    profile = {"name": name.strip(), "credit": credit.strip(),
               "cad": [app.strip() for app in cad]}
    atomic_json(home / "profile.json", profile)
    return read_profile(home)


def create_project(path, client, site, brief):
    project = Path(path).expanduser().resolve()
    validate_home(project)
    if not all(value.strip() for value in (client, site, brief)):
        raise ValueError("Client, site and brief must not be blank")
    project.mkdir(parents=True, exist_ok=True)
    text = f"# {project.name}\n\nClient: {client}\n\nSite: {site}\n\n## Brief\n\n{brief}\n"
    with (project / "README.md").open("x", encoding="utf-8") as stream:
        stream.write(text)
    return {"project": str(project), "readme": str(project / "README.md")}


def stage_revit(home):
    validate_home(home)
    source = PLUGIN_ROOT / "tools" / "revit" / "revit-mcp.extension"
    if not (source / "main.py").is_file():
        raise ValueError("Revit adapter missing: install a complete Architect Agent plugin")
    parent = home / "cad" / "revit"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / "revit-mcp.extension"
    temporary = Path(tempfile.mkdtemp(prefix=".staging-", dir=parent))
    backup = parent / f"revit-mcp.extension.previous-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        if target.exists():
            target.rename(backup)
        try:
            temporary.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"extension": str(target), "register_parent": str(parent),
            "previous": str(backup) if backup.exists() else None,
            "next_step": "Register this parent with pyRevit, enable Routes, restart Revit"}


def doctor(home):
    connections = {}
    for app, port in (("rhino", 1999), ("revit", 48884)):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                connections[app] = "listening; verify with an MCP inspection"
        except OSError:
            connections[app] = "not listening; start/restart CAD app (Revit also requires Routes)"
    return {"profile": read_profile(home), "uv": shutil.which("uv"),
            "platform": os.name, "connections": connections}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="Plugin state directory (default: ~/.architect-agent); does not select a project")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profile")
    commands.add_parser("doctor")
    commands.add_parser("stage-revit")
    configure_parser = commands.add_parser("configure")
    configure_parser.add_argument("--name", required=True)
    configure_parser.add_argument("--credit", required=True)
    configure_parser.add_argument("--cad", action="append", required=True)
    project_parser = commands.add_parser("project")
    project_parser.add_argument("path", nargs="?", default=".",
                                help="Project directory (default: current directory)")
    for field in ("client", "site", "brief"):
        project_parser.add_argument(f"--{field}", required=True)
    args = parser.parse_args()
    home = home_path(args.home)
    try:
        if args.command == "configure":
            result = configure(home, args.name, args.credit, args.cad)
        elif args.command == "project":
            result = create_project(args.path, args.client, args.site, args.brief)
        elif args.command == "stage-revit":
            result = stage_revit(home)
        elif args.command == "doctor":
            result = doctor(home)
        else:
            result = read_profile(home)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
