"""Command-line entry point and the two agent adapters."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .engine import Engine
from .repo import Repo, SafetyError

AGENTS = ("codex", "claude")


def install(agent: str) -> dict[str, list[str]]:
    skill = importlib.resources.files("leftoverkit").joinpath("SKILL.md").read_bytes()
    home = Path.home()
    roots = {
        "codex": Path(os.environ.get("CODEX_HOME") or home / ".codex"),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude"),
    }
    result: dict[str, list[str]] = {"installed": [], "already_installed": [], "conflicts": []}
    for name in AGENTS if agent == "all" else (agent,):
        target = roots[name] / "skills" / "leftoverkit" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink() or target.is_symlink():
            result["conflicts"].append(str(target))
            continue
        try:
            with target.open("xb") as stream:
                stream.write(skill)
            result["installed"].append(str(target))
        except FileExistsError:
            key = (
                "already_installed" if target.is_file() and target.read_bytes() == skill else "conflicts"
            )
            result[key].append(str(target))
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="leftoverkit", description=__doc__)
    root.add_argument(
        "-C", "--project", type=Path, default=Path.cwd(), help="Git checkout to operate on"
    )
    root.add_argument("--version", action="version", version="leftoverkit 0.2.0")
    commands = root.add_subparsers(dest="command", required=True)
    definitions = {
        "clean": "Move safe items to recoverable local storage",
        "scan": "Show what would move, without modifying the repository",
        "scratch": "Allocate a temporary directory for this task",
        "finish": "Mark a scratch allocation ready for cleanup",
        "register": "Register disposable files you created",
        "keep": "Exclude a file or scratch batch from subsequent cleanups",
        "undo": "Restore items from a cleanup batch",
        "purge": "Free space occupied by quarantine entries more than 14 days old",
        "install": "Install the agent skill for Codex, Claude Code, or both",
    }
    for name, help_text in definitions.items():
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--json", action="store_true", help="Emit machine-readable output")
        if name == "register":
            sub.add_argument("paths", nargs="+")
            sub.add_argument(
                "--temp", action="store_true", help="Register explicit paths in system temp"
            )
        elif name == "keep":
            sub.add_argument("path")
        elif name == "finish":
            sub.add_argument("id")
        elif name == "undo":
            sub.add_argument("id", nargs="?", default="latest")
        elif name == "install":
            sub.add_argument("--agent", choices=("all", *AGENTS), default="all")
    return root


def workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "install":
        return install(args.agent)

    engine = Engine(Repo(args.project))
    if args.command == "scan":
        return {"items": engine.scan()}
    if args.command == "clean":
        return engine.clean()
    if args.command == "scratch":
        return engine.scratch()
    if args.command == "finish":
        engine.finish(args.id)
        return {"finished": args.id}
    if args.command == "register":
        registered = engine.register_many(args.paths, temporary=args.temp)
        return registered[0] if len(registered) == 1 else {"registered": registered}
    if args.command == "keep":
        return {"kept": engine.keep(args.path)}
    if args.command == "undo":
        return engine.undo(args.id)
    return engine.purge()


def display(args: argparse.Namespace, data: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=True))
        return
    if args.command == "clean":
        print(f"Moved {data['moved']} item(s) to quarantine ({data['bytes']:,} file bytes).")
        if data["moved"]:
            print(f"Undo with: leftoverkit undo {data['batch']}")
    if "items" in data:
        for item in data["items"]:
            detail = f"  ({item['reason']})" if item.get("reason") else ""
            print(f"  {item['status']:<8} {item['path']!r}{detail}")
        if not data["items"] and args.command != "clean":
            print("Nothing to do.")
    elif "registered" in data:
        for item in data["registered"]:
            print(f"  {item['id']}  {item['path']!r}")
    elif "path" in data:
        print(data["path"])
        print(f"ID: {data['id']}")
    else:
        for key, value in data.items():
            print(f"{key.replace('_', ' ').capitalize()}: {value}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        data = workflow(args)
        display(args, data)
        return int(
            bool(data.get("conflicts"))
            or any(item["status"] == "error" for item in data.get("items", []))
        )
    except (OSError, SafetyError, ValueError, subprocess.SubprocessError) as error:
        if args.json:
            print(json.dumps({"error": str(error)}))
        else:
            print(f"leftoverkit: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
