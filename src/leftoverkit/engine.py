"""Candidate discovery and recoverable cleanup."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import stat
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .repo import (
    INTEGRATION,
    Repo,
    SafetyError,
    directory_fd,
    git,
    inside,
    inspect,
    private_dir,
    processes,
    read_json,
    rename_checked,
    require_private,
    sensitive_name,
    signature,
    system_temp_roots,
    write_json,
)

DAY = 86400
HOLD_DAYS = 14
REPORTS = {"playwright-report": "index.html", "test-results": ".last-run.json"}
WORKTREE_DIRS = (".worktree", ".worktrees", ".claude/worktrees")
ID = re.compile(r"^[a-f0-9]{16}$")
PROTECTED = {
    ".git",
    ".gitignore",
    ".gitattributes",
    "agents.md",
    "claude.md",
    ".agents",
    ".claude",
    ".codex",
    ".ssh",
    ".github",
    ".gitea",
    "artifacts",
    "deliverables",
    "docs",
    "outputs",
    "secrets",
}


def protected(path: Path) -> bool:
    return any(part.casefold() in PROTECTED or sensitive_name(part) for part in path.parts)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def in_use(path: Path, opened: set[Path]) -> bool:
    return any(inside(other, path) for other in opened)


class Engine:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.root = repo.root
        self.state = repo.state

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        private_dir(self.state)
        descriptor = os.open(self.state / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def registry(self) -> dict[str, Any]:
        return read_json(self.state / "registry.json", {"managed": {}, "held": []})

    def save_registry(self, data: dict[str, Any]) -> None:
        write_json(self.state / "registry.json", data)

    def scratch(self) -> dict[str, str]:
        with self.locked():
            directory = private_dir(private_dir(self.state / "scratch") / new_id())
            registry = self.registry()
            registry["managed"][directory.name] = {
                "path": str(directory),
                "kind": "scratch",
                "checkout": str(self.root),
                "finished": False,
            }
            self.save_registry(registry)
            return {"id": directory.name, "path": str(directory)}

    def register(self, value: str) -> dict[str, str]:
        return self.register_many([value])[0]

    def register_many(self, values: list[str], *, temporary: bool = False) -> list[dict[str, str]]:
        with self.locked():
            records = self.registry()
            registered = []
            kind = "registered-temp" if temporary else "registered"
            paths = dict.fromkeys(self.repo.input_path(value) for value in values)
            for path in paths:
                allowed = self.eligible_temp_path(path) if temporary else self.eligible_file_path(path)
                if not allowed or not stat.S_ISREG(path.lstat().st_mode):
                    scope = (
                        "operating-system temp directories outside Git checkouts"
                        if temporary
                        else "this checkout"
                    )
                    raise SafetyError(
                        f"Only untracked, unprotected regular files in {scope} may be registered."
                    )
                identity, _, _, _ = inspect(path)
                key = new_id()
                records["managed"][key] = {
                    "path": str(path),
                    "kind": kind,
                    "checkout": str(self.root),
                    "finished": True,
                    "identity": list(identity[:2]),
                }
                registered.append({"id": key, "path": str(path)})
            self.save_registry(records)
            return registered

    def eligible_temp_path(self, path: Path) -> bool:
        if not path.is_absolute() or path.resolve() != path:
            return False
        for root in system_temp_roots():
            if path == root or not inside(path, root) or protected(path.relative_to(root)):
                continue
            # A temp directory can contain a real checkout. Treat any Git marker as protected.
            return not any(
                os.path.lexists(parent / ".git") for parent in path.parents if inside(parent, root)
            )
        return False

    def eligible_file_path(self, path: Path) -> bool:
        return (
            inside(path, self.root)
            and path != self.root
            and path.resolve() == path
            and not protected(path.relative_to(self.root))
            and not self.repo.tracked(path)
            and not any(
                inside(path, Path(item["worktree"]).resolve())
                for item in self.repo.worktrees()
                if Path(item["worktree"]).resolve() != self.root
            )
        )

    def finish(self, key: str) -> None:
        with self.locked():
            registry = self.registry()
            row = registry["managed"].get(key)
            if row is None or row["kind"] != "scratch":
                raise SafetyError("Unknown scratch ID.")
            if not Path(row["path"]).is_dir():
                raise SafetyError("The scratch batch is no longer in its original location.")
            row["finished"] = True
            self.save_registry(registry)

    def keep(self, value: str) -> str:
        path = self.repo.input_path(value)
        with self.locked():
            registry = self.registry()
            scratch = self.state / "scratch"
            if inside(path, scratch) and path != scratch:
                path = scratch / path.relative_to(scratch).parts[0]
            registered = any(row["path"] == str(path) for row in registry["managed"].values())
            if not path.exists() or not (inside(path, self.root) or inside(path, scratch) or registered):
                raise SafetyError(
                    "Keep expects an existing project path, scratch batch, or registered file."
                )
            if str(path) not in registry["held"]:
                registry["held"].append(str(path))
                self.save_registry(registry)
            return str(path)

    def worktree_reason(self, row: dict[str, str], now: float) -> str:
        path = Path(row["worktree"]).resolve()
        roots = [self.repo.primary / folder for folder in WORKTREE_DIRS]
        if not any(path != root and inside(path, root) for root in roots):
            return "outside the managed worktree directories"
        if path == self.root or inside(self.root, path):
            return "current checkout"
        if "locked" in row or "prunable" in row or not path.is_dir():
            return "locked, missing, or prunable"
        if (
            path != Path(row["worktree"])
            or (path / ".git").is_symlink()
            or not (path / ".git").is_file()
        ):
            return "unexpected Git layout"
        if row.get("branch", "").removeprefix("refs/heads/") in INTEGRATION:
            return "integration branch"
        admin = Path(git(path, "rev-parse", "--absolute-git-dir").rstrip("\n")).resolve()
        if not inside(admin, self.repo.common / "worktrees"):
            return "unexpected Git metadata"
        if any(
            (admin / name).exists()
            for name in (
                "index.lock",
                "MERGE_HEAD",
                "CHERRY_PICK_HEAD",
                "REVERT_HEAD",
                "BISECT_START",
                "rebase-merge",
                "rebase-apply",
                "sequencer",
            )
        ):
            return "Git operation in progress"
        activity = [path, path / ".git", admin, admin / "HEAD", admin / "index", admin / "logs/HEAD"]
        if max(entry.stat().st_mtime for entry in activity if entry.exists()) >= now - 3 * DAY:
            return "active within 72 hours"
        head = row.get("HEAD", "")
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", head) or not self.repo.integrated(head):
            return "no matching remote-tracking integration branch"
        if not self.clean_worktree(path):
            return "contains changes, extra files, or submodules"
        return ""

    @staticmethod
    def clean_worktree(path: Path) -> bool:
        return not git(
            path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
        ) and not any(
            line.startswith("160000 ") for line in git(path, "ls-files", "--stage", "-z").split("\0")
        )

    def report_reason(self, path: Path) -> str:
        if not self.eligible_file_path(path) or not self.repo.ignored(path):
            return "not an ignored, wholly untracked project directory"
        marker = path / REPORTS[path.name]
        if marker.is_symlink() or not marker.is_file():
            return "missing Playwright marker"
        try:
            with os.fdopen(os.open(marker, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
                content = stream.read(256 * 1024)
            if path.name == "playwright-report":
                return (
                    "" if b"Playwright Test Report" in content else "missing Playwright report signature"
                )
            result = json.loads(content)
            if (
                isinstance(result, dict)
                and result.get("status") in {"passed", "failed", "interrupted", "timedout"}
                and isinstance(result.get("failedTests"), list)
            ):
                return ""
        except (OSError, ValueError):
            pass
        return "invalid Playwright marker"

    def candidates(self, opened: set[Path]) -> list[dict[str, Any]]:
        now = time.time()
        registry = self.registry()
        holds = [Path(item) for item in registry["held"]]
        scheduled: dict[Path, dict[str, Any]] = {}
        for key, row in registry["managed"].items():
            path = Path(row["path"])
            if path.exists() and (row["kind"] == "scratch" or row["checkout"] == str(self.root)):
                scheduled[path] = row | {"id": key}
        ignored = git(
            self.root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"
        )
        reports = {self.root / name for name in REPORTS}
        reports.update(
            self.root / relative
            for relative in ignored.split("\0")
            if relative.endswith("/") and Path(relative).name in REPORTS
        )
        for path in reports:
            if path.is_dir() or path.is_symlink():
                scheduled.setdefault(path, {"kind": "playwright", "path": str(path)})
        for name in ("tmp", ".tmp", "scratch", ".scratch"):
            path = self.root / name
            if path.exists() or path.is_symlink():
                scheduled.setdefault(path, {"kind": "legacy", "path": str(path)})
        for worktree in self.repo.worktrees()[1:]:
            path = Path(worktree["worktree"]).resolve()
            if not inside(path, self.state):
                scheduled[path] = {"kind": "worktree", "path": str(path), "git": worktree}
        results = []
        for path, row in sorted(scheduled.items()):
            reason = ""
            record = {"path": str(path), "kind": row["kind"], "status": "skipped"}
            try:
                if any(inside(path, held) or inside(held, path) for held in holds):
                    reason = "kept by the user"
                elif in_use(path, opened):
                    reason = "open in a running process"
                elif row["kind"] == "legacy":
                    reason = "unknown owner or purpose"
                elif row["kind"] == "worktree":
                    reason = self.worktree_reason(row["git"], now)
                    record["git"] = row["git"]
                else:
                    reason = self.file_reason(path, row, record, now)
            except (SafetyError, OSError) as error:
                reason = str(error)
            if reason:
                record["reason"] = reason
            else:
                record["status"] = "ready"
            results.append(record)
        return results

    def file_reason(self, path: Path, row: dict[str, Any], record: dict[str, Any], now: float) -> str:
        kind = row["kind"]
        if kind == "scratch" and (path.parent != self.state / "scratch" or path.name != row["id"]):
            return "invalid scratch path"
        if kind == "registered" and not self.eligible_file_path(path):
            return "tracked or outside the safe project paths"
        if kind == "registered-temp" and not self.eligible_temp_path(path):
            return "outside safe system temp paths or inside a Git checkout"
        if kind == "playwright":
            reason = self.report_reason(path)
            if reason:
                return reason
        current, digest, size, touched = inspect(path)
        if kind in {"registered", "registered-temp"} and list(current[:2]) != row["identity"]:
            return "registered file was replaced"
        if kind == "scratch" and not row["finished"] and touched >= now - 2 * DAY:
            return "scratch allocation still active"
        if kind == "playwright" and touched >= now - 7 * DAY:
            return "generated report is newer than seven days"
        record.update(signature=list(current), fingerprint=digest, bytes=size)
        return ""

    def scan(self) -> list[dict[str, Any]]:
        return self.candidates(processes())

    def clean(self) -> dict[str, Any]:
        with self.locked():
            entries = self.scan()
            ready = [item for item in entries if item["status"] == "ready"]
            result: dict[str, Any] = {"batch": None, "moved": 0, "bytes": 0, "items": entries}
            if not ready:
                return result
            batch_id = new_id()
            folder = private_dir(private_dir(self.state / "batches") / batch_id)
            items = private_dir(folder / "items")
            journal = folder / "journal.json"
            batch: dict[str, Any] = {"id": batch_id, "created": time.time(), "items": []}
            opened = processes()
            for index, entry in enumerate(ready):
                path = Path(entry["path"])
                destination = items / str(index)
                line = entry | {"target": str(destination), "status": "pending"}
                batch["items"].append(line)
                write_json(journal, batch)
                try:
                    if in_use(path, opened):
                        raise SafetyError("Item became busy before it could be moved.")
                    if entry["kind"] == "worktree":
                        reason = self.worktree_reason(entry["git"], time.time())
                        if (
                            reason
                            or entry["git"] not in self.repo.worktrees()
                            or in_use(path, processes())
                        ):
                            raise SafetyError(reason or "Worktree changed or became busy.")
                        git(self.repo.root, "worktree", "move", "--", str(path), str(destination))
                    else:
                        current, digest, _, _ = inspect(path)
                        if digest != entry["fingerprint"]:
                            raise SafetyError("Item changed since inspection.")
                        if entry["kind"] == "registered" and not self.eligible_file_path(path):
                            raise SafetyError("Item is now tracked or outside the safe project paths.")
                        if entry["kind"] == "registered-temp" and not self.eligible_temp_path(path):
                            raise SafetyError("Item no longer qualifies as a system temp file.")
                        if entry["kind"] == "playwright" and (reason := self.report_reason(path)):
                            raise SafetyError(reason)
                        rename_checked(path, destination, current)
                        line["quarantine_fingerprint"] = inspect(destination)[1]
                    entry["status"] = line["status"] = "moved"
                    result["moved"] += 1
                    result["bytes"] += entry.get("bytes", 0)
                except (OSError, SafetyError) as error:
                    entry.update(status="error", reason=str(error))
                    line["reason"] = str(error)
                write_json(journal, batch)
            result["batch"] = batch_id
            return result

    def batches(self) -> list[dict[str, Any]]:
        directory = self.state / "batches"
        if not directory.exists():
            return []
        require_private(directory)
        batches = []
        for folder in directory.iterdir():
            if ID.fullmatch(folder.name):
                require_private(folder)
                journal = read_json(folder / "journal.json")
                if journal and journal.get("id") == folder.name:
                    batches.append(journal)
        return sorted(batches, key=lambda item: (item["created"], item["id"]), reverse=True)

    def undo(self, batch_id: str) -> dict[str, Any]:
        with self.locked():
            batch = next(
                (batch for batch in self.batches() if batch_id in ("latest", batch["id"])), None
            )
            if batch is None:
                raise SafetyError("No matching cleanup batch.")
            journal = self.state / "batches" / batch["id"] / "journal.json"
            results = []
            opened = processes()
            for index, line in enumerate(batch["items"]):
                source = journal.parent / "items" / str(index)
                target = Path(line["path"])
                if line["status"] in {"restored", "purged"} or not source.exists():
                    continue
                try:
                    if os.path.lexists(target):
                        raise SafetyError("Original path already exists; both copies were kept.")
                    if in_use(source, opened):
                        raise SafetyError("The quarantined item is in use.")
                    if line["kind"] == "worktree":
                        with directory_fd(target.parent):
                            git(self.root, "worktree", "move", "--", str(source), str(target))
                    else:
                        registry = self.registry()
                        if str(target) not in registry["held"]:
                            registry["held"].append(str(target))
                            self.save_registry(registry)
                        rename_checked(source, target, signature(source.lstat()))
                    line["status"] = "restored"
                    write_json(journal, batch)
                    results.append({"path": str(target), "status": "restored"})
                except (OSError, SafetyError) as error:
                    results.append({"path": str(target), "status": "error", "reason": str(error)})
            return {"batch": batch["id"], "items": results}

    def purge(self) -> dict[str, Any]:
        results = []
        with self.locked():
            batches = [
                item for item in self.batches() if item["created"] < time.time() - HOLD_DAYS * DAY
            ]
            opened = processes() if batches else set()
            for batch in batches:
                directory = self.state / "batches" / batch["id"]
                for index, item in enumerate(batch["items"]):
                    target = directory / "items" / str(index)
                    if item["status"] != "moved" or not target.exists():
                        continue
                    try:
                        if in_use(target, opened):
                            raise SafetyError("The quarantined item is in use.")
                        if item["kind"] == "worktree":
                            row = next(
                                (row for row in self.repo.worktrees() if row["worktree"] == str(target)),
                                None,
                            )
                            if (
                                row is None
                                or row.get("HEAD") != item["git"].get("HEAD")
                                or row.get("branch") != item["git"].get("branch")
                                or not self.repo.integrated(row["HEAD"])
                                or not self.clean_worktree(target)
                            ):
                                raise SafetyError(
                                    "The quarantined worktree changed or is no longer integrated."
                                )
                            git(self.root, "worktree", "remove", "--", str(target))
                        else:
                            if inspect(target)[1] != item.get("quarantine_fingerprint"):
                                raise SafetyError("The quarantined item changed.")
                            if target.is_dir():
                                shutil.rmtree(target)
                            else:
                                target.unlink()
                        item["status"] = "purged"
                        write_json(directory / "journal.json", batch)
                        results.append({"path": item["path"], "status": "purged"})
                    except (OSError, SafetyError) as error:
                        results.append({"path": item["path"], "status": "error", "reason": str(error)})
        return {"items": results}
