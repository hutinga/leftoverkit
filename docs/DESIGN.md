# Scope, evidence and recovery

## Scope

| Command scope | Which items can move or be restored |
| --- | --- |
| Default checkout | Unscoped artifacts from the current checkout and recognized reports in that checkout. Ready worktrees appear as review items. |
| `--task ID` | Only the scratch and registered files explicitly recorded for that task and checkout, and cleanup batches made in the same scope. |
| `--repo` | From the primary checkout, includes shared managed scratch, eligible linked worktrees and artifacts from the primary checkout. Restores may select batches across the repository. |

A task ID separates operations by intent. A process with the same local account can still deliberately invoke a wider scope. Old registry entries from 0.2 belong to their recorded checkout. Old journals can be inspected through `batches --repo` if ownership cannot be inferred.

## Discovery and protection

The scan walks the current checkout with a bounded entry count, including report folders nested under ignored parents. It skips dependency trees, nested repositories, Git internals and protected paths, and labels a limited or unavailable scan. Git-ignored Playwright output requires a runner marker, enough age and no tracked content. Suspicious logs, scripts, patches or captures with unknown provenance are always advisory.

`register` accepts exact, untracked artifact paths in a checkout. Source and ordinary configuration files are rejected even before they are staged. Temporary scripts belong in managed scratch. Registered files outside the repository must be in operating-system temporary directories and outside any Git checkout. Open-file verification is required before moves. Git and lsof are invoked from system locations, independent of the caller's PATH.

Old merged worktrees may contain ignored `node_modules` or `.venv` with their expected marker. Untracked files, unexpected ignored files, modified files, submodules, held worktrees and open files block cleanup. Permanent removal also checks identified cache directories for sensitive names. Worktree size is a bounded logical-byte measurement and can be partial.

## Recovery and storage

The journal is persisted before each move. Same-volume no-overwrite renames keep a recoverable copy. Exact registered files on another volume use a private directory on their original volume. Directory and worktree moves across filesystems can fail without moving the item. Moving files to quarantine does not free space.

`undo` defaults to the newest batch with items left in the selected scope. It recreates missing parent directories through no-follow directory handles and refuses to overwrite new files. Use `batches` to find older IDs. Restoring a file holds it until `unkeep PATH`.

The default state is local to Git metadata. `leftoverkit config --init` writes a private `config.json` with `scratch_hours`, `worktree_hours`, `report_days`, `review_hours`, `retention_days` and `scan_limit`. To keep state outside the checkout, set `LEFTOVERKIT_STATE_DIR` to an existing private directory outside it. The tool creates a separate child for each repository path. Keep both the state and any on-volume quarantine directories when making backups. A fresh clone alone cannot recover old local state.

`purge` removes eligible quarantine entries after retention and removes records that are no longer used. Git worktrees stay registered and keep their branch checked out until recovery or purge.
