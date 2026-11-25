"""Verify a first scan in a populated Git checkout with no LeftoverKit registrations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from demo import DAY, old_worktree, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=shutil.which("leftoverkit"))
    args = parser.parse_args()
    if not args.cli:
        parser.error("Install LeftoverKit or pass --cli.")
    cli = str(Path(args.cli).resolve())
    with tempfile.TemporaryDirectory(prefix="leftoverkit-discovery-") as temp:
        root = Path(temp).resolve()
        run("git", "init", "-qb", "main", cwd=root)
        run("git", "config", "user.name", "Fixture", cwd=root)
        run("git", "config", "user.email", "fixture@example.invalid", cwd=root)
        baseline = {
            ".gitignore": "generated/\nnode_modules/\n.env\n.worktree/\n",
            "app.py": "def main(): pass\n",
            "package.json": "{}\n",
            "stable.log": "tracked evidence\n",
        }
        for path, content in baseline.items():
            (root / path).write_text(content)
        run("git", "add", ".", cwd=root)
        run("git", "commit", "-qm", "Fixture baseline", cwd=root)
        run("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=root)
        old = time.time() - 9 * DAY
        leftovers = {
            "frontend/generated/playwright-report/index.html": "<title>Playwright Test Report</title>\n",
            "frontend/generated/stale-build.log": "old build diagnostic\n",
            "tmp/repro-focus.py": "print('one-off reproduction')\n",
            "tmp/draft.patch": "unapplied synthetic patch\n",
            "tmp/export.csv": "row,score\nx,1\n",
        }
        for name, content in leftovers.items():
            path = root / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text(content)
            os.utime(path, (old, old))
        report = root / "frontend/generated/playwright-report"
        os.utime(report, (old, old))
        (root / ".env").write_text("EXAMPLE=synthetic-value\n")

        linked = root / ".worktree/old-tooling"
        run("git", "worktree", "add", "-qb", "old-tooling", str(linked), "HEAD", cwd=root)
        (linked / "node_modules").mkdir()
        (linked / "node_modules/example.js").write_text("export const example = 1;\n")
        old_worktree(root, linked)
        result = json.loads(run(cli, "scan", "--json", cwd=root))
        by_name = {Path(item["path"]).relative_to(root).as_posix(): item for item in result["items"]}
        report_name = "frontend/generated/playwright-report"
        assert by_name[report_name]["status"] == "ready", result
        for name in (*list(leftovers)[1:], ".worktree/old-tooling"):
            assert by_name[name]["status"] == "review", result
        assert ".env" not in by_name and "stable.log" not in by_name
        assert not (root / ".git/leftoverkit").exists()
        assert all((root / path).read_text() == content for path, content in leftovers.items())
        for name, item in sorted(by_name.items()):
            print(
                f"{item['status']:<7} {item.get('bytes', 0):>5,} B  {name}  {item.get('evidence', '')}"
            )


if __name__ == "__main__":
    main()
