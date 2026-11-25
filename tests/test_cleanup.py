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
    file = engine.root / "scratch.log"
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
    source = engine.root / "source.log"
    source.write_text("one")
    link = engine.root / "link.txt"
    link.symlink_to(source)
    with pytest.raises(SafetyError, match="symbolic link"):
        engine.register(link.name)
    hardlink = engine.root / "hard.log"
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
    path = engine.root / "check.once.log"
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
    stale = engine.root / "tmp/old.log"
    stale.write_text("review me")
    age(stale)
    assert "newer" in items(engine.scan())[report.name]["reason"]
    age(report, html)
    git(engine.root, "add", "-f", str(html))
    assert "wholly untracked" in items(engine.scan())[report.name]["reason"]
    git(engine.root, "rm", "--cached", str(html))
    result = engine.clean()
    assert result["moved"] == 1
    findings = items(result["items"])
    assert findings[malformed.name]["status"] == "skipped"
    assert findings["old.log"]["status"] == "review"
    assert stale.exists()


def test_worktrees_keep_unique_commits_dirty_ignored_and_locked(engine):
    engine = Engine(engine.repo, whole_repo=True)
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
    engine = Engine(engine.repo, whole_repo=True)
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
    assert json.loads(capsys.readouterr().out) == {"items": [], "warnings": []}
    assert cli.main(["-C", str(engine.root), "undo", "--json"]) == 1
    assert "No restorable" in json.loads(capsys.readouterr().out)["error"]


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


def test_task_isolation_in_shared_checkout_and_linked_worktree(engine):
    first = Engine(engine.repo, task=engine.start()["task"])
    same_checkout = Engine(engine.repo, task=engine.start()["task"])
    linked, _ = worktree(engine, "parallel")
    other = Engine(Repo(linked), task=Engine(Repo(linked)).start()["task"])
    allocated = [active_scratch(worker) for worker in (first, same_checkout, other)]
    for worker, (allocation, _, _) in zip((first, same_checkout, other), allocated, strict=True):
        worker.finish(allocation["id"])
    with pytest.raises(SafetyError, match="Unknown task"):
        Engine(engine.repo, task=other.task)
    with pytest.raises(SafetyError, match="Unknown scratch"):
        first.finish(allocated[1][0]["id"])

    assert engine.clean()["moved"] == 0
    assert [Path(item["path"]) for item in first.scan()] == [allocated[0][1]]
    receipt = first.clean()
    assert receipt["moved"] == 1
    assert not allocated[0][1].exists()
    assert all(item[1].exists() for item in allocated[1:])
    with pytest.raises(SafetyError, match="No restorable"):
        same_checkout.undo(receipt["batch"])
    with pytest.raises(SafetyError, match="No restorable"):
        engine.undo(receipt["batch"])
    assert first.undo("latest")["items"][0]["status"] == "restored"


def test_task_cannot_adopt_same_artifact_twice(engine):
    first = Engine(engine.repo, task=engine.start()["task"])
    other = Engine(engine.repo, task=engine.start()["task"])
    log = engine.root / "run.log"
    log.write_text("first task")
    assert first.register(log.name) == first.register(log.name)
    with pytest.raises(SafetyError, match="already registered"):
        other.register(log.name)
    assert other.clean()["moved"] == 0 and log.exists()


def test_scan_discovers_unregistered_artifacts_under_ignored_parent(engine):
    root = engine.root
    (root / ".gitignore").write_text("generated/\n")
    report = root / "frontend/generated/playwright-report"
    report.mkdir(parents=True)
    marker = report / "index.html"
    marker.write_text("<title>Playwright Test Report</title>")
    diagnostic = root / "frontend/generated/old-build.log"
    diagnostic.write_text("diagnostic")
    age(marker, report, diagnostic)
    scan = items(engine.scan())
    assert scan["playwright-report"]["status"] == "ready"
    assert scan["old-build.log"]["status"] == "review"
    assert scan["old-build.log"]["bytes"] == len("diagnostic")
    assert scan["old-build.log"]["evidence"]
    assert not engine.state.exists()
    assert engine.clean()["moved"] == 1
    assert diagnostic.exists()


def test_new_untracked_application_source_cannot_be_registered(engine):
    src = engine.root / "src"
    src.mkdir()
    new = src / "new_feature.py"
    new.write_text("production source")
    with pytest.raises(SafetyError, match="managed scratch"):
        engine.register(str(new))
    age(new)
    assert engine.clean()["moved"] == 0
    assert new.read_text() == "production source"


def test_latest_undo_advances_and_recreates_folders(engine):
    receipts = []
    for directory in ("batch-a", "batch-b"):
        folder = engine.root / directory
        folder.mkdir()
        log = folder / "output.log"
        log.write_text(directory)
        engine.register(str(log))
        receipts.append(engine.clean()["batch"])
        folder.rmdir()
    assert engine.batch_list(20)[0]["restorable"] == 1
    for receipt, directory in zip(reversed(receipts), ("batch-b", "batch-a"), strict=True):
        result = engine.undo("latest")
        assert result["batch"] == receipt and result["items"][0]["status"] == "restored"
        assert (engine.root / directory / "output.log").read_text() == directory
    assert engine.clean()["moved"] == 0
    engine.keep("batch-b/output.log", release=True)
    assert engine.clean()["moved"] == 1


def test_worktree_quarantine_and_purge_allow_known_dependency_caches(engine):
    engine = Engine(engine.repo, whole_repo=True)
    (engine.root / "package.json").write_text("{}\n")
    (engine.root / ".gitignore").write_text(".worktree/\nnode_modules/\n.venv/\n.env\n")
    git(engine.root, "add", "package.json", ".gitignore")
    git(engine.root, "commit", "-qm", "dependency manifests")
    git(engine.root, "update-ref", "refs/remotes/origin/main", "HEAD")
    child, watched = worktree(engine, "old-tooling")
    for name, file in (("node_modules", "some-package.js"), (".venv", "pyvenv.cfg")):
        cache = child / name
        cache.mkdir()
        (cache / file).write_text("test dependency")
    age(*watched)
    result = engine.clean()
    assert result["moved"] == 1 and not child.exists()
    journal = engine.state / "batches" / result["batch"] / "journal.json"
    batch = json.loads(journal.read_text())
    batch["created"] -= 15 * DAY
    write_json(journal, batch)
    assert engine.purge()["items"][0]["status"] == "purged"
    assert len(engine.repo.worktrees()) == 1


def test_cross_volume_temp_quarantine_can_be_recovered(engine, monkeypatch):
    import tempfile

    alternate = Path("/dev/shm")
    if not alternate.is_dir() or alternate.stat().st_dev == engine.root.stat().st_dev:
        pytest.skip("requires a second writable filesystem")
    with tempfile.TemporaryDirectory(dir=alternate) as ext:
        external = Path(ext)
        monkeypatch.setattr(module, "system_temp_roots", lambda: {external})
        path = external / "run.log"
        path.write_text("data")
        engine.register_many([str(path)], temporary=True)
        result = engine.clean()
        assert result["moved"] == 1 and not path.exists()
        assert list(external.glob(".leftoverkit-quarantine-*/item"))
        assert engine.undo(result["batch"])["items"][0]["status"] == "restored"
        assert path.read_text() == "data" and not list(external.glob(".leftoverkit-quarantine-*"))


def test_scan_limit_and_failed_occupancy_check_are_visible(engine, monkeypatch):
    with engine.locked():
        write_json(engine.state / "config.json", {"scan_limit": 1})
    safer = Engine(engine.repo)
    (engine.root / "a.log").write_text("a")
    (engine.root / "b.log").write_text("b")

    def unavailable():
        raise SafetyError("lsof unavailable")

    monkeypatch.setattr(module, "processes", unavailable)
    safer.scan(read_only=True)
    assert any("open files" in warning.casefold() for warning in safer.warnings)
    assert any("entry limit" in warning for warning in safer.warnings)
    with pytest.raises(SafetyError, match="lsof"):
        safer.clean()


def test_undo_refuses_symlink_parent_when_recreating_tree(engine):
    original = engine.root / "once"
    original.mkdir()
    output = original / "run.log"
    output.write_text("recover me")
    engine.register(str(output))
    result = engine.clean()
    original.rmdir()
    elsewhere = engine.root / "elsewhere"
    elsewhere.mkdir()
    original.symlink_to(elsewhere, target_is_directory=True)
    assert engine.undo(result["batch"])["items"][0]["status"] == "error"
    assert list(elsewhere.iterdir()) == []
    assert engine.batch_list(20)[0]["restorable"] == 1


def test_external_state_stays_separate_for_each_repository(engine, monkeypatch, tmp_path_factory):
    state = tmp_path_factory.mktemp("leftoverkit-external").resolve()
    state.chmod(0o700)
    monkeypatch.setenv("LEFTOVERKIT_STATE_DIR", str(state))
    relocated = Engine(Repo(engine.root))
    other = tmp_path_factory.mktemp("another-checkout").resolve()
    git(other, "init", "-q")
    second = Engine(Repo(other))
    assert relocated.state.parent == second.state.parent == state
    assert relocated.state != second.state
    relocated.start()
    assert relocated.state.is_dir() and not second.state.exists()


def test_tool_lookup_ignores_executables_in_path(engine, tmp_path, monkeypatch):
    binary = tmp_path / "fake-tool"
    binary.mkdir()
    fake = binary / "git"
    fake.write_text("#!/bin/sh\nexit 99\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary))
    assert Repo(engine.root).root == engine.root
    assert Path(filesystem.system_tool("git", ("/usr/bin", "/bin"))).parent != binary


def test_kept_worktree_can_report_measured_bytes_without_moving_it(engine):
    child, _ = worktree(engine, "recent-build")
    cache = child / "node_modules"
    cache.mkdir()
    (cache / "package.js").write_text("sample build")
    scan = items(engine.scan(read_only=True))
    assert scan[child.name]["status"] == "skipped"
    assert scan[child.name]["bytes"] >= len("sample build")
    assert child.exists()


def test_legacy_registry_and_journal_restore_in_the_recorded_checkout(engine):
    allocation, directory, source = active_scratch(engine)
    engine.finish(allocation["id"])
    with engine.locked():
        registry = engine.registry()
        row = registry["managed"][allocation["id"]]
        row.pop("task")
        row.pop("created")
        engine.save_registry(registry)
    result = engine.clean()
    assert result["moved"] == 1
    journal = engine.state / "batches" / result["batch"] / "journal.json"
    receipt = json.loads(journal.read_text())
    for key in ("task", "checkout", "whole_repo"):
        receipt.pop(key)
    write_json(journal, receipt)
    assert not directory.exists()
    assert engine.undo("latest")["items"][0]["status"] == "restored"
    assert source.read_text() == "scratch"


def test_worktree_purge_preserves_secrets_inside_dependency_cache(engine):
    root = engine.root
    (root / "package.json").write_text("{}\n")
    (root / ".gitignore").write_text(".worktree/\nnode_modules/\n")
    git(root, "add", "package.json", ".gitignore")
    git(root, "commit", "-qm", "fixture manifests")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    child, watched = worktree(engine, "dependency-protection")
    cache = child / "node_modules/package"
    cache.mkdir(parents=True)
    (cache / ".env").write_text("EXAMPLE=protected")
    age(*watched)
    repo_cleaner = Engine(engine.repo, whole_repo=True)
    result = repo_cleaner.clean()
    assert result["moved"] == 1
    journal = engine.state / "batches" / result["batch"] / "journal.json"
    batch = json.loads(journal.read_text())
    batch["created"] -= 15 * DAY
    write_json(journal, batch)
    assert repo_cleaner.purge()["items"][0]["status"] == "error"
    assert repo_cleaner.undo(result["batch"])["items"][0]["status"] == "restored"
    assert (cache / ".env").read_text() == "EXAMPLE=protected"
