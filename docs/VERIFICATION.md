# LeftoverKit 0.3.0 verification

| Check | Observed result |
| --- | --- |
| macOS, Python 3.14 | 31 passed, 1 skipped, 84% statement coverage. The skipped test needs a second writable filesystem. |
| Linux ARM64, Python 3.11 | 32 passed, 85% statement coverage. The installed wheel and fixtures ran offline. The cross-volume test moved and restored an exact file between the test filesystem and a separate mounted filesystem. |
| First scan | A synthetic existing checkout with zero registrations yielded one ready report and five review findings. The report was inside an ignored parent directory. The scan wrote no state. |
| Task isolation | The CLI separated two tasks in one checkout. Regression tests also cover two linked worktrees, duplicate registration, and a 0.2 journal with inferred ownership. |
| Recovery | Sequential undo picks older unapplied batches, recreates missing directories without following symlinks, and preserves collisions. Worktree tests include ignored dependencies and a protected file inside an ignored cache. |
| Public replay | The synthetic run moved and restored five known objects. They contained 991 files and one worktree. The browser replay verified pointer, keyboard, mobile, both languages, and missing-data feedback. |
| Static checks | Ruff, Pyright, JavaScript syntax, Git whitespace checks, and packaging metadata checks passed. |

The fixtures verify product behavior with public synthetic data. They do not establish how often people discover something worth cleaning in their own repositories. Claude Code's model-driven flow has not been tested.
