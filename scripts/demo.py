"""Run the public cleanup and restore story in a disposable Git project."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

DAY = 86400


def run(*command: str, cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def old_worktree(repo: Path, path: Path) -> None:
    admin = Path(run("git", "rev-parse", "--absolute-git-dir", cwd=path))
    old = time.time() - 4 * DAY
    for member in (path, path / ".git", admin, admin / "HEAD", admin / "index", admin / "logs" / "HEAD"):
        os.utime(member, (old, old))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=shutil.which("leftoverkit"), help="Path to the installed CLI")
    parser.add_argument(
        "--json", action="store_true", help="Emit a portable record of the observed demo"
    )
    args = parser.parse_args()
    if args.cli is None:
        parser.error("Install leftoverkit or pass --cli.")
    cli = str(Path(args.cli).resolve())
    with tempfile.TemporaryDirectory(prefix="leftoverkit-demo-") as temporary:
        repo = Path(temporary).resolve()
        run("git", "init", "-q", "-b", "main", cwd=repo)
        run("git", "config", "user.name", "LeftoverKit Demo", cwd=repo)
        run("git", "config", "user.email", "demo@example.invalid", cwd=repo)
        (repo / "app.py").write_text('print("hello")\n')
        (repo / ".gitignore").write_text("playwright-report/\n.worktree/\n")
        run("git", "add", ".gitignore", "app.py", cwd=repo)
        run("git", "commit", "-qm", "Demo baseline", cwd=repo)
        run("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)

        scratch = json.loads(run(cli, "scratch", "--json", cwd=repo))
        work = Path(scratch["path"])
        files = {
            "repro.py": b'print("temporary debug")\n',
            "browser.log": b"Runner finished.\n",
            "screenshot.png": bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
                "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
            ),
        }
        for name, data in files.items():
            (work / name).write_bytes(data)
        run(cli, "finish", scratch["id"], cwd=repo)

        report = repo / "playwright-report"
        report.mkdir()
        marker = report / "index.html"
        marker.write_text("<title>Playwright Test Report</title>\n")
        old = time.time() - 8 * DAY
        for path in (marker, report):
            os.utime(path, (old, old))
        unknown = repo / "tmp"
        unknown.mkdir()
        (unknown / "old-notes.txt").write_text("Origin unknown. Keep this.")
        worktree = repo / ".worktree" / "finished-fix"
        run("git", "worktree", "add", "-qb", "finished-fix", str(worktree), "HEAD", cwd=repo)
        old_worktree(repo, worktree)

        clean = json.loads(run(cli, "clean", "--repo", "--json", cwd=repo))
        assert clean["moved"] == 3, clean
        assert not any(path.exists() for path in (work, report, worktree))
        assert (repo / "app.py").read_text() == 'print("hello")\n'
        assert (unknown / "old-notes.txt").is_file()
        restored = json.loads(run(cli, "undo", "--repo", clean["batch"], "--json", cwd=repo))
        assert len(restored["items"]) == 3, restored
        assert all((work / name).read_bytes() == data for name, data in files.items())
        assert marker.is_file()
        assert run("git", "branch", "--show-current", cwd=worktree) == "finished-fix"

        evidence = {
            "moved": clean["moved"],
            "items": ["agent scratch (3 files)", "Playwright report", "merged linked worktree"],
            "kept": ["app.py (tracked source)", "tmp/old-notes.txt (unknown owner)"],
            "restored": len(restored["items"]),
            "content_verified": True,
        }
        if args.json:
            print(json.dumps(evidence, indent=2))
        else:
            print("$ leftoverkit clean")
            for item in evidence["items"]:
                print(f"  moved    {item}")
            for item in evidence["kept"]:
                print(f"  kept     {item}")
            print("\n$ leftoverkit undo")
            print(f"  restored {evidence['restored']} items")
            print("  verified original bytes and worktree branch")


if __name__ == "__main__":
    main()
