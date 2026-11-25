import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from leftoverkit import cli
from leftoverkit import engine as module
from leftoverkit import repo as filesystem
from leftoverkit.engine import DAY, Engine
from leftoverkit.repo import Repo, SafetyError, git, write_json


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "processes", set)
    root = tmp_path.resolve()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.invalid")
    (root / ".gitignore").write_text("playwright-report/\ntest-results/\n.worktree/\n.env\n")
    (root / "app.py").write_text("print('tracked')\n")
    git(root, "add", ".gitignore", "app.py")
    git(root, "commit", "-qm", "initial")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return Engine(Repo(root))


def age(*paths, days=8):
    previous = time.time() - days * DAY
    for path in paths:
        os.utime(path, (previous, previous))


def active_scratch(engine, name="debug.py"):
    allocation = engine.scratch()
    directory = Path(allocation["path"])
    source = directory / name
    source.write_text("scratch")
    return allocation, directory, source


def worktree(engine, name, *, detached=False):
    path = engine.root / ".worktree" / name
    args = ("--detach",) if detached else ("-b", name)
    git(engine.root, "worktree", "add", "-q", *args, str(path), "HEAD")
    admin = Path(git(path, "rev-parse", "--absolute-git-dir").strip())
    watched = (path, path / ".git", admin, admin / "HEAD", admin / "index", admin / "logs/HEAD")
    return path, watched


def items(entries):
    return {Path(item["path"]).name: item for item in entries}


def test_scan_is_read_only(engine):
    assert engine.scan() == []
    assert not engine.state.exists()


def test_finished_batch_moves_and_undo_keeps_original_bytes(engine):
    allocation, directory, source = active_scratch(engine)
    assert engine.clean()["moved"] == 0
    engine.finish(allocation["id"])
    result = engine.clean()
    assert result["moved"] == 1 and result["bytes"] == 7
    assert not directory.exists()
    assert engine.clean()["moved"] == 0
    assert engine.undo(result["batch"])["items"][0]["status"] == "restored"
    assert source.read_text() == "scratch"
    assert engine.clean()["moved"] == 0
    assert engine.undo(result["batch"])["items"] == []


def test_abandoned_scratch_and_keep(engine):
    _, directory, source = active_scratch(engine)
    age(source, directory, days=3)
    assert engine.scan()[0]["status"] == "ready"
    assert engine.keep(str(source)) == str(directory)
    assert engine.clean()["items"][0]["reason"] == "kept by the user"


def test_busy_scratch_and_nested_secret_are_kept(engine, monkeypatch):
    allocation, _, source = active_scratch(engine)
    engine.finish(allocation["id"])
    monkeypatch.setattr(module, "processes", lambda: {source})
    assert engine.clean()["items"][0]["reason"] == "open in a running process"
    monkeypatch.setattr(module, "processes", set)
    secret = source.parent / ".env"
    secret.write_text("synthetic fixture")
    assert "sensitive" in engine.clean()["items"][0]["reason"]
    assert secret.exists()


def test_registered_file_has_to_stay_untracked_and_unreplaced(engine):
    file = engine.root / "scratch.py"
    file.write_text("one")
    engine.register(file.name)
    git(engine.root, "add", file.name)
    assert "tracked" in engine.clean()["items"][0]["reason"]
    git(engine.root, "rm", "--cached", file.name)
    changed = engine.root / "replacement"
    changed.write_text("two")
    changed.replace(file)
    assert "replaced" in engine.clean()["items"][0]["reason"]
    assert file.read_text() == "two"
    with pytest.raises(SafetyError, match="untracked"):
        engine.register("app.py")
    assert engine.repo.tracked(engine.root / "APP.py")


def test_register_rejects_hard_links_symlinks_and_protected_paths(engine, tmp_path):
    source = engine.root / "source.txt"
    source.write_text("one")
    link = engine.root / "link.txt"
    link.symlink_to(source)
    with pytest.raises(SafetyError, match="symbolic link"):
        engine.register(link.name)
    hardlink = engine.root / "hard.txt"
    hardlink.hardlink_to(source)
    with pytest.raises(SafetyError, match="hard-linked"):
        engine.register(source.name)
    private = engine.root / ".env"
    private.write_text("private")
    with pytest.raises(SafetyError, match="unprotected"):
        engine.register(private.name)
    with pytest.raises(SafetyError):
        engine.register(str(tmp_path.parent / "outside"))


def test_undo_never_overwrites_new_files(engine):
    path = engine.root / "check.once.py"
    path.write_text("old")
    engine.register(path.name)
    batch = engine.clean()["batch"]
    path.write_text("new")
    error = engine.undo(batch)["items"][0]
    assert error["status"] == "error" and path.read_text() == "new"
    path.unlink()
    assert engine.undo("latest")["items"][0]["status"] == "restored"
    assert path.read_text() == "old"


def test_playwright_markers_unknown_tmp_and_git_stop_unsafe_moves(engine):
    report = engine.root / "playwright-report"
    report.mkdir()
    html = report / "index.html"
    html.write_text("<title>Playwright Test Report</title>")
    malformed = engine.root / "test-results"
    malformed.mkdir()
    (malformed / ".last-run.json").write_text("{}")
    (engine.root / "tmp").mkdir()
    assert "newer" in items(engine.scan())[report.name]["reason"]
    age(report, html)
    git(engine.root, "add", "-f", str(html))
    assert "wholly untracked" in items(engine.scan())[report.name]["reason"]
    git(engine.root, "rm", "--cached", str(html))
    result = engine.clean()
    assert result["moved"] == 1
    findings = items(result["items"])
    assert findings[malformed.name]["status"] == "skipped"
    assert findings["tmp"]["reason"] == "unknown owner or purpose"


def test_worktrees_keep_unique_commits_dirty_ignored_and_locked(engine):
    merged, good = worktree(engine, "merged")
    dirty, modified = worktree(engine, "dirty")
    (dirty / ".env").write_text("local")
    unique, committed = worktree(engine, "unique", detached=True)
    git(unique, "commit", "-qm", "detached", "--allow-empty")
    locked, locked_age = worktree(engine, "locked")
    git(engine.root, "worktree", "lock", str(locked))
    age(*good, *modified, *committed, *locked_age)
    batch = engine.clean()
    found = items(batch["items"])
    assert batch["moved"] == 1
    assert "extra files" in found[dirty.name]["reason"]
    assert "remote-tracking" in found[unique.name]["reason"]
    assert "locked" in found[locked.name]["reason"]
    assert not merged.exists()
    quarantine = next(
        Path(row["worktree"])
        for row in engine.repo.worktrees()
        if row.get("branch") == "refs/heads/merged"
    )
    assert quarantine.is_relative_to(engine.state / "batches")
    assert engine.undo(batch["batch"])["items"][0]["status"] == "restored"
    assert git(merged, "branch", "--show-current").strip() == "merged"


def test_interrupted_journal_is_recoverable(engine):
    allocation, directory, source = active_scratch(engine)
    engine.finish(allocation["id"])
    result = engine.clean()
    journal = engine.state / "batches" / result["batch"] / "journal.json"
    batch = json.loads(journal.read_text())
    batch["items"][0]["status"] = "pending"
    write_json(journal, batch)
    assert engine.undo("latest")["items"][0]["status"] == "restored"
    assert directory.exists() and source.read_text() == "scratch"


def test_apply_rechecks_fingerprint_before_rename(engine, monkeypatch):
    allocation, _, source = active_scratch(engine)
    engine.finish(allocation["id"])
    real = engine.scan

    def scan():
        candidates = real()
        source.write_text("changed during scan")
        return candidates

    monkeypatch.setattr(engine, "scan", scan)
    outcome = engine.clean()["items"][0]
    assert outcome["status"] == "error" and "changed" in outcome["reason"]
    assert source.read_text() == "changed during scan"


def test_purge_respects_retention_and_skips_changed_archive(engine):
    for count in range(2):
        allocation, _, _ = active_scratch(engine)
        engine.finish(allocation["id"])
        result = engine.clean()
        journal = engine.state / "batches" / result["batch"] / "journal.json"
        batch = json.loads(journal.read_text())
        assert engine.purge()["items"] == []
        batch["created"] -= 15 * DAY
        write_json(journal, batch)
        if count == 1:
            (journal.parent / "items/0/debug.py").write_text("new data")
        assert engine.purge()["items"][0]["status"] == ("purged" if count == 0 else "error")


def test_worktree_purge_releases_branch(engine):
    old, watched = worktree(engine, "merged")
    age(*watched)
    result = engine.clean()
    journal = engine.state / "batches" / result["batch"] / "journal.json"
    batch = json.loads(journal.read_text())
    batch["created"] -= 15 * DAY
    write_json(journal, batch)
    assert engine.purge()["items"][0]["status"] == "purged"
    assert len(engine.repo.worktrees()) == 1
    assert git(engine.root, "show-ref", "--verify", "refs/heads/merged")
    assert not old.exists()


def test_linux_or_mac_rename_refuses_collision(engine):
    source = engine.root / "old"
    target = engine.root / "new"
    source.write_text("original")
    target.write_text("existing")
    with filesystem.directory_fd(engine.root) as directory, pytest.raises(OSError) as raised:
        filesystem.rename_no_replace(directory, source.name, directory, target.name)
    assert raised.value.errno == errno.EEXIST
    assert target.read_text() == "existing"


def test_cli_json_install_and_conflict(engine, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    assert cli.main(["install", "--json"]) == 0
    installed = json.loads(capsys.readouterr().out)["installed"]
    assert len(installed) == 2 and all(Path(path).exists() for path in installed)
    assert cli.main(["install", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["already_installed"]) == 2
    Path(installed[0]).write_text("custom")
    assert cli.main(["install", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["conflicts"] == [installed[0]]
    assert cli.main(["-C", str(engine.root), "scan", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"items": []}
    assert cli.main(["-C", str(engine.root), "undo", "--json"]) == 1
    assert "No matching" in json.loads(capsys.readouterr().out)["error"]


def test_real_open_file_is_seen_by_lsof(engine, monkeypatch):
    monkeypatch.setattr(module, "processes", filesystem.processes)
    allocation, _, source = active_scratch(engine)
    engine.finish(allocation["id"])
    program = "import sys; f = open(sys.argv[1]); print('ready', flush=True); sys.stdin.readline()"
    with subprocess.Popen(
        [sys.executable, "-c", program, str(source)],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as worker:
        try:
            assert worker.stdout.readline().strip() == "ready"
            result = engine.clean()
            assert result["moved"] == 0 and result["items"][0]["reason"] == "open in a running process"
            assert source.is_file()
        finally:
            worker.communicate(input="\n", timeout=5)


def test_register_multiple_temp_files_checks_scope_and_preserves_undo(engine, tmp_path, monkeypatch):
    temporary = tmp_path / "fake-system-temp"
    temporary.mkdir()
    monkeypatch.setattr(module, "system_temp_roots", lambda: {temporary})
    log = temporary / "once.log"
    diff = temporary / "draft.patch"
    log.write_text("test output")
    diff.write_text("patch data")
    private = temporary / ".env"
    private.write_text("local")
    tree = temporary / "checkout"
    tree.mkdir()
    git(tree, "init", "-q")
    tracked = tree / "tracked.py"
    tracked.write_text("example")
    with pytest.raises(SafetyError):
        engine.register_many([str(log), str(private)], temporary=True)
    assert engine.scan() == []
    with pytest.raises(SafetyError):
        engine.register_many([str(tracked)], temporary=True)
    assert len(engine.register_many([str(log), str(diff)], temporary=True)) == 2
    result = engine.clean()
    assert result["moved"] == 2
    assert private.is_file() and tracked.is_file()
    assert not log.exists() and not diff.exists()
    assert len(engine.undo(result["batch"])["items"]) == 2
    assert log.read_text() == "test output" and diff.read_text() == "patch data"


def test_discovers_nested_ignored_playwright_report(engine):
    gitignore = engine.root / ".gitignore"
    gitignore.write_text(gitignore.read_text() + "frontend/playwright-report/\n")
    report = engine.root / "frontend/playwright-report"
    report.mkdir(parents=True)
    marker = report / "index.html"
    marker.write_text("<title>Playwright Test Report</title>")
    age(report, marker)
    assert items(engine.scan())[report.name]["status"] == "ready"
    result = engine.clean()
    assert result["moved"] == 1 and not report.exists()
    assert engine.undo(result["batch"])["items"][0]["status"] == "restored"
