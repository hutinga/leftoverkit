---
name: leftoverkit
description: Inspect old artifacts in a Git checkout or clean only artifacts assigned to the current coding task.
---

# LeftoverKit

Use `leftoverkit scan --json` for a read-only inventory of an existing checkout. Explain evidence and leave review items in place. Never broaden to `--repo` unless the user explicitly asks for repository-wide cleanup.

For new scratch files, create a task with `leftoverkit start --json` and record its task ID. Allocate scratch with `leftoverkit scratch --task TASK_ID --json`. Keep deliverables in their intended project locations. Once the task and its subprocesses finish, use `leftoverkit finish --task TASK_ID SCRATCH_ID`.

Register exact non-source artifacts produced by this task with `leftoverkit register --task TASK_ID PATH ...`. For exact files outside Git in operating-system temporary storage, add `--temp`. If the task ID or ownership is uncertain, produce a read-only scan instead of applying cleanup.

Use `leftoverkit scan --task TASK_ID --json` before `leftoverkit clean --task TASK_ID --json`. Report the task ID and batch ID. Recover with `leftoverkit undo --task TASK_ID BATCH_ID`. Respect skipped items and restore conflicts.
