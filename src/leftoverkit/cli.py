"""Command-line entry point and the two agent adapters."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.resources
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .engine import Engine
from .repo import Repo, SafetyError, write_json

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
    root.add_argument(
        "--version", action="version", version="leftoverkit " + importlib.metadata.version("leftoverkit")
    )
    commands = root.add_subparsers(dest="command", required=True)
    definitions = {
        "clean": "Move safe items to recoverable local storage",
        "scan": "Find old leftovers and show evidence, without modifying the repository",
        "start": "Start a task scoped to this checkout and print its ID",
        "batches": "List cleanup batches and recoverable bytes",
        "config": "Show or initialize local settings",
        "scratch": "Allocate a temporary directory for this task",
        "finish": "Mark a scratch allocation ready for cleanup",
        "register": "Register disposable files you created",
        "keep": "Exclude a file or scratch batch from subsequent cleanups",
        "unkeep": "Remove an explicit or post-restore hold",
        "undo": "Restore items from a cleanup batch",
        "purge": "Permanently free space after the configured retention period",
        "install": "Install the agent skill for Codex, Claude Code, or both",
    }
    for name, help_text in definitions.items():
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--json", action="store_true", help="Emit machine-readable output")
        if name in {"scan", "clean", "undo", "batches", "purge", "scratch", "register", "finish"}:
            scope = sub.add_mutually_exclusive_group()
            scope.add_argument(
                "--task", metavar="ID", help="Limit this operation to one task in this checkout"
            )
            if name in {"scan", "clean", "undo", "batches", "purge"}:
                scope.add_argument(
                    "--repo", action="store_true", help="Include shared scratch and linked worktrees"
                )
        if name == "register":
            sub.add_argument("paths", nargs="+")
            sub.add_argument(
                "--temp", action="store_true", help="Register explicit paths in system temp"
            )
        elif name in {"keep", "unkeep"}:
            sub.add_argument("path")
        elif name == "finish":
            sub.add_argument("id")
        elif name == "undo":
            sub.add_argument("id", nargs="?", default="latest")
        elif name == "config":
            sub.add_argument(
                "--init", action="store_true", help="Write the default file if it does not exist"
            )
        elif name in {"scan", "batches"}:
            sub.add_argument(
                "--limit",
                type=int,
                choices=range(1, 101),
                default=12 if name == "scan" else 20,
                metavar="1..100",
            )
        elif name == "install":
            sub.add_argument("--agent", choices=("all", *AGENTS), default="all")
    return root


def workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "install":
        return install(args.agent)

    engine = Engine(
        Repo(args.project), task=getattr(args, "task", None), whole_repo=getattr(args, "repo", False)
    )
    if args.command == "start":
        return engine.start()
    if args.command == "scan":
        findings = engine.scan(read_only=True)
        return {"items": findings, "warnings": engine.warnings}
    if args.command == "batches":
        return {"batches": engine.batch_list(args.limit)}
    if args.command == "config":
        file = engine.state / "config.json"
        defaults = asdict(engine.settings)
        if args.init:
            with engine.locked():
                if not os.path.lexists(file):
                    write_json(file, defaults)
        return {"settings_path": str(file), "settings": defaults}
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
    if args.command == "unkeep":
        return {"released": engine.keep(args.path, release=True)}
    if args.command == "undo":
        return engine.undo(args.id)
    return engine.purge()


def display(args: argparse.Namespace, data: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=True))
        return
    if args.command == "clean":
        print(f"Moved {data['moved']} item(s) to quarantine ({data['bytes']:,} logical bytes).")
        if data["moved"]:
            scope = (" --task " + args.task) if args.task else (" --repo" if args.repo else "")
            print(f"Undo with: leftoverkit undo{scope} {data['batch']}")
    if args.command == "scan":
        ready = sum(item["status"] == "ready" for item in data["items"])
        review = sum(item["status"] == "review" for item in data["items"])
        skipped = len(data["items"]) - ready - review
        size = sum(
            item.get("bytes", 0) for item in data["items"] if item["status"] in {"ready", "review"}
        )
        kept_size = sum(item.get("bytes", 0) for item in data["items"] if item["status"] == "skipped")
        print(
            f"Read-only scan. Ready {ready} · Review {review} · Kept {skipped}. "
            f"Measured {size:,} logical bytes for ready/review items and {kept_size:,} for kept items."
        )
    for warning in data.get("warnings", []):
        print(f"  {warning}")
    if "items" in data:
        shown = data["items"]
        if args.command == "scan":
            priorities = {"ready": 0, "review": 1, "skipped": 2}
            shown = sorted(
                shown, key=lambda item: (priorities[item["status"]], -item.get("bytes", 0), item["path"])
            )
            if len(shown) > args.limit:
                print(f"  Showing {args.limit} of {len(shown)} findings. Use --json for the full scan.")
            shown = shown[: args.limit]
        for item in shown:
            detail = " · ".join(item[key] for key in ("evidence", "reason") if item.get(key))
            size = f"  {item['bytes']:,} B" if "bytes" in item else ""
            measured = " (partial)" if item.get("size_complete") is False else ""
            print(
                f"  {item['status']:<8} {item['path']!r}{size}{measured}"
                + (f"  {detail}" if detail else "")
            )
        if not data["items"] and args.command != "clean":
            print("Nothing to do.")
    elif "batches" in data:
        for item in data["batches"]:
            print(f"  {item['id']}  {item['restorable']} restorable  {item['bytes']:,} B")
        if not data["batches"]:
            print("No cleanup batches in this scope.")
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
