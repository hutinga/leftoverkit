# Product and safety contract

A developer installs LeftoverKit once and asks their coding agent to clean up. The same local CLI handles the entire action without asking for a file-by-file decision.

- **Managed scratch** has an allocation ID. Finishing an allocation makes it eligible immediately. An abandoned allocation qualifies after 48 hours without writes. An explicit hold is persistent.
- **Legacy files** require stronger evidence. Only Git-ignored Playwright output with a valid runner marker becomes eligible automatically after seven days. Unknown scratch paths can appear in the report. Tracked files are read-only.
- **Linked worktrees** qualify after 72 hours of inactivity, when they live under a recognized folder in the primary project and their HEAD is already in a local remote-tracking integration ref. A busy, locked, dirty or unmerged checkout is left in place. Git moves the checkout into quarantine without force. The linked branch stays checked out until the worktree is restored or purged.
- **Explicit registration** supports multiple exact project paths or system temp files outside Git checkouts. The registry records file identity and rejects protected paths.
- **Clean** rescans the repo, checks current file identity and occupation, and records its work before moving it. Files go to recoverable local storage in the Git metadata. **Undo** restores to the original location and reports conflicts. **Purge** is an explicit command after 14 days.
- **Automation** runs the same CLI. Scheduled invocation can call `leftoverkit -C PATH clean`. CLI checks are independent of whether an agent follows the installed skill.
- **Trust boundary** is one local Git project and this tool's local state. Project branches cannot grant extra path access. The CLI makes no network calls and cannot detect every external tool that intends to use a path later. A running process and a persistent Git worktree lock can both protect a checkout.

This release targets macOS and Linux, with two thin skill integrations. Remote actions and automatic edits to tracked code are outside this release. The release fixtures are entirely synthetic.
