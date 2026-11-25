# LeftoverKit

**Your AI finished the job. Now let it clean up.**

**991 temporary files → 0 in the workspace → 991 restored.**
One actual CLI run in a synthetic Git project. The source, final evidence and open log stay put.

[![991 temporary files move, then come back](docs/media/cleanup.gif)](docs/DEMO.md)

[Try the interactive replay](docs/DEMO.md) · [What agents leave behind](docs/SCENARIOS.md) · [中文](docs/README.zh-CN.md)

Tell Codex or Claude Code **“Clean up the temporary files you made.”** Or run **`leftoverkit clean`**. It moves eligible leftovers to quarantine and prints an undo command.

## Install

Requires Python 3.11+, Git and `lsof`. Targets macOS and Linux.

Install from GitHub.

```sh
uv tool install git+https://github.com/hutinga/leftoverkit.git && leftoverkit install
```

`leftoverkit install` adds the skill to Codex and Claude Code. Reopen the agent if the newly installed skill is missing. For CLI-only use, run the install command without `&& leftoverkit install`. To install from a checkout, run `uv tool install .`. You can also install a built wheel with `pipx install /path/to/the.whl`.

## Use

```sh
leftoverkit clean         # cleans eligible items and prints an undo ID
leftoverkit undo          # restores the latest batch, preserving any new files
leftoverkit scan          # preview without making changes
```

| What it finds | Default action |
| --- | --- |
| Agent scratch batches and explicitly registered files | Finished batches are ready right away. Abandoned scratch batches are eligible after 48 hours. |
| Git-ignored Playwright reports, including nested outputs with a valid runner marker | Quarantine after seven days without changes. |
| Clean linked worktrees under conventional project folders | Quarantine after 72 hours if the commit is already on a local remote-tracking integration branch. |
| Unknown `tmp/` or `scratch/`, protected paths, active worktrees and dirty worktrees | Show the reason and leave them in place. |

An agent allocates a place with `leftoverkit scratch --json`, then runs `leftoverkit finish ID` when its tests and subprocesses are done. It can register disposable untracked project files it created with `leftoverkit register PATH ...`, or exact paths in system temp with `leftoverkit register --temp PATH ...`. If a scratch batch is worth keeping, run `leftoverkit keep PATH`. A hold on a file inside a batch keeps the whole batch.

Files go into private local storage under the repository’s Git metadata. Quarantined worktrees stay registered with Git until restored or purged. Their branches remain checked out during that time. `leftoverkit purge` frees space from batches at least 14 days old. `leftoverkit -C /path/to/repo clean` is suitable for a scheduler. The tool operates locally and sends no data.

## Development

```sh
uv run --with pytest pytest -q
uv build
```

MIT licensed.
