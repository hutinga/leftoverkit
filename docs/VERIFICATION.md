# LeftoverKit 0.2.0 verification

| Check | Observed result |
| --- | --- |
| macOS 26.5.1, Python 3.14 | 18 tests passed, 87% statement coverage. A separate Python 3.12 environment installed the wheel and verified the large demo. |
| Linux ARM64, Python 3.11 | 18 tests passed, 87% statement coverage. The release wheel and both fixtures ran with the container network disabled. |
| Large fixture | The real CLI moved and restored 991 files in six categories and one merged worktree. Content hashes, the original branch and protected files were checked. The generated browser data matched on both systems. |
| Guardrails | Tests covered a held-open file, staged files, filename aliases, ignored secrets, unmerged and locked worktrees, a new file at the restore destination, nested Playwright paths, and exact system-temp registration. |
| Interactive replay | Chrome verified desktop pointer cleanup, keyboard undo, mobile touch, Chinese/English, a 320px browser width, reduced motion and unavailable fixture data. The standalone page worked offline. |
| Agent adapters | Both installations were checked in isolated directories. A local Codex app-server discovered the skill in the initial build. Claude Code's model-driven flow remains untested. |
| Static checks | Ruff, Pyright, JavaScript syntax and Git whitespace checks passed. |
| Release artifacts | The wheel and source distribution passed Twine checks. The wheel includes the skill and license. It has no runtime Python dependencies. |

All public demo data is synthetic. The local work history audit stays outside the source distribution.
