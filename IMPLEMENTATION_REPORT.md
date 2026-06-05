# LingTai Simple v0.7 Implementation Report

## Summary

v0.7 adds a real **Claude Code L2 local-edit worker** on top of v0.6's real Keychain vault, model API test, git Time Machine / rollback, WeChat bridge endpoint, and Claude Code L1 read-only analysis worker.

The new L2 path is intentionally narrow: it can modify local files, but it cannot commit, open PRs, or merge. Those remain confirmation-queue records until separate real executors are implemented.

## Backend changes

- Version metadata updated to v0.7.
- Added `CC_WORKTREE_DIR` under the system temp directory.
- `/api/cc/request` now handles:
  - `level=1`: real Claude Code read-only analysis.
  - `level=2`: real Claude Code local edit.
  - `level>=3`: confirmation queue only, `real_executor=false`.
- L2 local edit flow:
  1. Reject empty tasks, suspected secrets, missing cost/local-change confirmation, missing `claude`, or dirty main worktree.
  2. Create a safety git ref before running.
  3. Create an isolated detached git worktree.
  4. Run `claude --print` with `--permission-mode acceptEdits`.
  5. Allow only `Read,Grep,Glob,Edit,Write`; disallow `Bash,NotebookEdit,WebFetch,WebSearch`.
  6. Convert worktree changes to a binary patch.
  7. Run `python3 -m py_compile` on main Python entry files.
  8. Run a high-confidence secret scan without printing matched secrets.
  9. Apply the patch to the main repo only if validation passes.
  10. Write a report under `data/cc_runs/<run_id>.md` with changed files, checks, output, and diff preview.

## Frontend changes

- Updated version and labels to v0.7.
- Claude Code button now says L1/L2 are real.
- Claude modal explains:
  - L1 is read-only analysis.
  - L2 uses an isolated git worktree and may modify repo files.
  - L3+ commit/PR/merge still only enter the confirmation queue.
- Run history displays changed files, report path, output preview, and run status through existing `cc_runs` state.

## Docs and safety

- README now documents exact L1 and L2 usage.
- `.gitignore` includes runtime Claude Code reports; temporary L2 worktrees are created under the system temp directory.
- L2 does not store or print secrets, and refuses task descriptions that look like credentials.
- L2 does not start a shell through Claude; Bash is explicitly disallowed.
- L2 does not commit, PR, or merge.

## Validation performed

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

Expected self-check output:

```text
OK LingTai Simple v0.7 self-check passed
```

Self-check does not burn external Claude Code tokens. It validates that L1/L2 reject without confirmation and that L3+ still routes to confirmation only.

## Remaining work

1. Real L3 commit executor with diff preview, author identity control, and confirmation gate.
2. Real PR creation executor using 圆酱 GitHub identity and secret-safe token handling.
3. Real merge executor with explicit WeChat/UI confirmation.
4. Persistent WeChat bridge runner using the existing LingTai WeChat MCP as the only poller.
5. Full LingTai runtime / skills / memory integration.
