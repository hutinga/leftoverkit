# What AI leaves behind

| What the agent leaves | Common example | What LeftoverKit does |
| --- | --- | --- |
| Visual checks | Screenshots, short clips, contact sheets, browser traces | Collects finished scratch batches and exact files the agent registers. Keep the batch if its visual evidence is part of the delivery. |
| Build and test residue | Logs, JSON reports, Playwright results under a frontend package | Collects registered files and detects stale Git-ignored Playwright reports with a valid runner marker, including nested outputs. |
| One-off code | `probe-once.py`, repro scripts, API checks in the checkout or system temp | A finished agent can register multiple exact paths at once. Source already tracked by Git stays in the project. |
| Scratch exports | CSV and JSON extracts, intermediate rendered assets, handoff fragments | Collects finished scratch and registered files. Ambiguous exports and formal deliveries stay. |
| Patches and backups | Patch drafts, before-state archives, recovery exports | Drafts in managed scratch can expire. Backups with unclear provenance stay. |
| Parallel development | Old worktrees, detached diagnostics, unmerged fixes | Quarantines eligible, merged, clean worktrees. Leaves active, locked, dirty or unmerged worktrees. |
| Live processes | A Vite preview, browser session, local test runner | Protects paths open in a process. The process keeps running. |
| Tool downloads and caches | Browser bundles, dependencies, model downloads, build caches | Files in managed scratch follow its expiry rules. Shared caches and tool installations stay. |
| Credentials and deliverables | `.env`, local keys, release evidence, final output folders, unknown `tmp/` | Protected paths and unknown leftovers stay. |

Ownership records for processes and caches, and a reviewable Git diff for committed temporary code, are follow-up cases.
