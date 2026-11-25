"""Generate the verified large-scale showcase data in a disposable repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from demo import DAY, old_worktree, run

GROUPS = {"screenshots": 420, "logs": 290, "reports": 160, "exports": 60, "scripts": 37, "patches": 24}
EXTENSIONS = {
    "screenshots": "png",
    "logs": "log",
    "reports": "json",
    "exports": "csv",
    "scripts": "py",
    "patches": "diff",
}


def create_files(root: Path, kind: str, count: int) -> list[Path]:
    created = []
    for index in range(count):
        path = root / f"{kind}-{index:03d}.{EXTENSIONS[kind]}"
        path.write_bytes(f"Synthetic {kind} fixture {index}\n".encode())
        created.append(path)
    return created


def sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare(repo: Path, external: Path, cli: str) -> tuple[dict[str, list[Path]], dict[str, Path]]:
    run("git", "init", "-qb", "main", cwd=repo)
    run("git", "config", "user.name", "Synthetic Demo", cwd=repo)
    run("git", "config", "user.email", "demo@example.invalid", cwd=repo)
    (repo / "app.py").write_text("def health(): return True\n")
    (repo / ".gitignore").write_text(".env\n.worktree/\nfrontend/playwright-report/\n")
    run("git", "add", "app.py", ".gitignore", cwd=repo)
    run("git", "commit", "-qm", "baseline", cwd=repo)
    run("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)

    # Realistic categories with deliberately synthetic payloads.
    current = json.loads(run(cli, "scratch", "--json", cwd=repo))
    scratch = Path(current["path"])
    files = {
        "screenshots": create_files(scratch, "screenshots", GROUPS["screenshots"]),
        "logs": create_files(scratch, "logs", GROUPS["logs"] - 1),
        "exports": create_files(scratch, "exports", GROUPS["exports"]),
        "scripts": create_files(scratch, "scripts", GROUPS["scripts"] - 1),
        "patches": create_files(scratch, "patches", GROUPS["patches"]),
    }
    run(cli, "finish", current["id"], cwd=repo)

    log = external / "browser-debug.log"
    log.write_text("Synthetic detached browser log\n")
    repro = repo / "probe-once.py"
    repro.write_text('print("synthetic repro")\n')
    run(cli, "register", "--temp", str(log), cwd=repo)
    run(cli, "register", repro.name, cwd=repo)
    files["logs"].append(log)
    files["scripts"].append(repro)

    report = repo / "frontend/playwright-report"
    report.mkdir(parents=True)
    marker = report / "index.html"
    marker.write_text("<title>Playwright Test Report</title>\n")
    files["reports"] = [marker, *create_files(report, "reports", GROUPS["reports"] - 1)]
    old = time.time() - 9 * DAY
    for path in [report, *files["reports"]]:
        os.utime(path, (old, old))

    keep = {
        "source": repo / "app.py",
        "secret": repo / ".env",
        "unknown": repo / "tmp/old-notes.txt",
        "delivery": repo / "outputs/acceptance-evidence.txt",
        "busy": repo / "running-preview.log",
    }
    for key in ("secret", "unknown", "delivery", "busy"):
        path = keep[key]
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"Synthetic protected {key}\n")
    run(cli, "register", keep["busy"].name, cwd=repo)
    return files, keep


def exercise(repo: Path, external: Path, cli: str) -> dict[str, object]:
    files, keep = prepare(repo, external, cli)
    moved = [path for paths in files.values() for path in paths]
    protected = list(keep.values())
    original = sha256(moved)
    keep_hash = sha256(protected)
    worktree = repo / ".worktree/merged-fix"
    unmerged = repo / ".worktree/in-flight"
    run("git", "worktree", "add", "-qb", "merged-fix", str(worktree), "HEAD", cwd=repo)
    run("git", "worktree", "add", "-qb", "in-flight", str(unmerged), "HEAD", cwd=repo)
    run("git", "commit", "-qm", "unique change", "--allow-empty", cwd=unmerged)
    old_worktree(repo, worktree)
    old_worktree(repo, unmerged)

    program = "import sys; handle=open(sys.argv[1]); print('ready', flush=True); sys.stdin.readline()"
    with subprocess.Popen(
        [sys.executable, "-c", program, str(keep["busy"])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as worker:
        try:
            assert worker.stdout and worker.stdout.readline().strip() == "ready"
            clean = json.loads(run(cli, "clean", "--json", cwd=repo))
            assert len(moved) == 991
            assert clean["moved"] == 5, clean
            assert not any(path.exists() for path in [*moved, worktree])
            reasons = {Path(item["path"]).name: item.get("reason") for item in clean["items"]}
            assert reasons[keep["busy"].name] == "open in a running process"
            assert "remote-tracking" in reasons[unmerged.name]
            assert sha256(protected) == keep_hash and unmerged.is_dir()

            undo = json.loads(run(cli, "undo", clean["batch"], "--json", cwd=repo))
            assert len(undo["items"]) == 5 and all(
                item["status"] == "restored" for item in undo["items"]
            )
            assert sha256(moved) == original
            assert run("git", "branch", "--show-current", cwd=worktree) == "merged-fix"
        finally:
            worker.communicate(input="\n", timeout=5)

    return {
        "synthetic": True,
        "files": GROUPS,
        "moved_files": len(moved),
        "restored_files": len(moved),
        "protected": list(keep),
        "moved_worktrees": 1,
        "untouched_worktrees": 1,
        "original_bytes_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=shutil.which("leftoverkit"))
    parser.add_argument("--browser-data", type=Path)
    args = parser.parse_args()
    if not args.cli:
        parser.error("Install leftoverkit or pass --cli.")
    with tempfile.TemporaryDirectory(prefix="leftoverkit-showcase-", dir="/tmp") as temp:
        root = Path(temp).resolve()
        repo, external = root / "project", root / "external"
        repo.mkdir()
        external.mkdir()
        data = exercise(repo, external, str(Path(args.cli).resolve()))
        if args.browser_data:
            args.browser_data.write_text("window.demoEvidence = " + json.dumps(data, indent=2) + ";\n")
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
