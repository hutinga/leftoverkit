"""Bounded, read-only discovery in an existing checkout."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .repo import normalize_path

REPORTS = {"playwright-report": "index.html", "test-results": ".last-run.json"}
CACHES = {"node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
SCRATCH_NAMES = {"tmp", "temp", "scratch", ".tmp", ".scratch", "debug"}
ATTACHMENTS = {".png", ".jpg", ".jpeg", ".webp", ".webm", ".mp4", ".csv", ".json", ".jsonl", ".zip"}
ONE_OFF_CODE = {".py", ".sh", ".js", ".cjs", ".mjs", ".ts", ".go", ".rb", ".ps1"}
ARTIFACTS = {".log", ".trace", ".har", ".patch", ".diff", ".tmp", ".bak"}
REVIEW_TEXT = {".txt", ".md", ".tar", ".gz", ".tgz"}


def dependency_cache(path: Path) -> bool:
    marker = path.parent / "package.json" if path.name == "node_modules" else path / "pyvenv.cfg"
    return path.name in {"node_modules", ".venv"} and marker.is_file() and not marker.is_symlink()


def suspicious(path: Path) -> str:
    suffix = path.suffix.casefold()
    name = path.name.casefold()
    scratch = bool({part.casefold() for part in path.parts[:-1]} & SCRATCH_NAMES)
    if suffix in ONE_OFF_CODE and (
        scratch or name.startswith(("probe-", "repro-", "scratch-", "debug-"))
    ):
        return "untracked one-off script name or scratch location"
    if suffix in ARTIFACTS or (scratch and suffix in ATTACHMENTS | REVIEW_TEXT):
        return "untracked artifact extension or scratch location"
    if suffix in ATTACHMENTS and name.startswith(("screenshot-", "trace-", "capture-")):
        return "untracked capture name"
    return ""


def discover(
    root: Path,
    tracked: set[str],
    blocked: set[Path],
    protected: Callable[[Path], bool],
    limit: int,
    cutoff: float,
) -> tuple[set[Path], list[dict[str, Any]], str | None]:
    pending = [root]
    reports: set[Path] = set()
    findings: list[dict[str, Any]] = []
    visited = unavailable = measured_caches = 0
    while pending and visited < limit:
        directory = pending.pop()
        try:
            # Bound how many names we read even if a directory contains millions of files.
            with os.scandir(directory) as listing:
                for entry in listing:
                    if visited >= limit:
                        return (
                            reports,
                            findings,
                            f"Scan reached its {limit:,}-entry limit; more files may exist.",
                        )
                    visited += 1
                    path = Path(entry.path)
                    relative = path.relative_to(root)
                    if path in blocked or protected(relative) or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name in REPORTS:
                            reports.add(path)
                        elif measured_caches < 5 and dependency_cache(path):
                            size, complete = estimated_bytes(path, limit=5_000)
                            findings.append(
                                {
                                    "path": path,
                                    "kind": "legacy",
                                    "bytes": size,
                                    "size_complete": complete,
                                    "evidence": "dependency cache with a project marker",
                                }
                            )
                            measured_caches += 1
                        elif entry.name not in CACHES and not os.path.lexists(path / ".git"):
                            pending.append(path)
                        continue
                    evidence = suspicious(relative)
                    if not evidence or normalize_path(relative.as_posix()) in tracked:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if (
                        stat.S_ISREG(info.st_mode)
                        and info.st_uid == os.getuid()
                        and info.st_mtime < cutoff
                        and info.st_nlink == 1
                    ):
                        findings.append(
                            {"path": path, "kind": "legacy", "bytes": info.st_size, "evidence": evidence}
                        )
        except OSError:
            unavailable += 1
    warning = (
        f"Scan reached its {limit:,}-entry limit; more files may exist."
        if pending
        else f"Could not read {unavailable} director{'y' if unavailable == 1 else 'ies'}."
        if unavailable
        else None
    )
    return reports, findings, warning


def estimated_bytes(root: Path, limit: int = 25_000) -> tuple[int, bool]:
    if root.is_symlink() or not root.is_dir():
        return 0, True
    pending = [root]
    count = total = 0
    complete = True
    while pending:
        try:
            with os.scandir(pending.pop()) as listing:
                for entry in listing:
                    if count >= limit:
                        return total, False
                    count += 1
                    if entry.name == ".git" or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            complete = False
    return total, complete
