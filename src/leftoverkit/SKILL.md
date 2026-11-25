---
name: leftoverkit
description: Safely clean up temporary files left by coding agents. Use when asked to clean up, remove temporary validation artifacts, or clean up after a coding task. During a task, use the scratch command for throwaway scripts, logs, and screenshots.
---

# Clean up with LeftoverKit

Run commands from the current project. LeftoverKit needs Git, Python 3.11+, and lsof for automatic moves on macOS or Linux.

- Before generating disposable files, run `leftoverkit scratch --json` and use the returned absolute path. Keep the returned ID.
- Put deliverables in their intended project location. If an entire scratch batch needs to be retained, run `leftoverkit keep PATH`.
- Once the task and any subprocesses are done, run `leftoverkit finish ID`. For a disposable project file outside the scratch directory, run `leftoverkit register PATH` only if you created it and have finished using it. Pass multiple exact paths in one command. For files you created in system temp, run `leftoverkit register --temp PATH ...`. Use exact paths from the task history.
- When asked to clean up, check the current task's tool output for any disposable project files you created outside a scratch batch. Use the registration command above for files whose origin and purpose you can establish. Then run `leftoverkit clean --json`. It applies the safe items automatically. Use `leftoverkit scan --json` for a preview-only request.
- Report what moved along with its undo ID. Leave anything reported as held or skipped to the existing project workflow. Do not work around a skip with other deletion commands.
- To reverse a cleanup, run `leftoverkit undo BATCH` with the reported ID. If the original path has been reused, leave both copies and report the conflict.
