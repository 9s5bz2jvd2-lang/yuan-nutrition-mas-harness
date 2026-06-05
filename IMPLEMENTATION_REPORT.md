# LingTai Simple v0.8 Implementation Report

## Summary

v0.8 adds a real **Claude Code L3 local git commit executor** on top of v0.7's real Keychain vault, model API test, git Time Machine / rollback, WeChat bridge endpoint, Claude Code L1 read-only analysis worker, and Claude Code L2 local-edit worker.

The new L3 path is intentionally narrow: it can create a local git commit after explicit confirmation, but it cannot push, open PRs, or merge. PR/merge remain confirmation-queue records until separate real executors are implemented.

## Changed files

- `server.py`
  - Version metadata updated to v0.8.
  - Added commit author defaults for Wang Runyuan.
  - Added `prepare_cc_commit_approval()` for L3 confirmation preview.
  - Added `git_commit_apply_real()` for confirmation-gated local git commit.
  - Added approved-file-list persistence in approval records.
  - Updated health boundaries and Claude Code L4/L5 copy.
- `static/index.html`, `static/app.js`
  - Updated UI copy to v0.8 and clarified L3 local commit is real.
  - PR/merge remain not real.
- `scripts/self_check.py`
  - Updated version assertions to v0.8.
  - Tests L3 queues a real executor confirmation without approving it.
- `data/state.example.json`
  - Updated demo title to v0.8.
- `README.md`
  - Documents exact real/not-real boundaries.

## L3 commit safety design

1. L3 does not call Claude Code or any external model.
2. It inspects the current git worktree and queues a `code_commit` approval only when:
   - git is available;
   - there are uncommitted/untracked-unignored files;
   - changed file count is not excessive;
   - high-confidence secret scan passes;
   - Python compile check passes.
3. The approval stores:
   - sanitized commit message;
   - reviewed changed file list;
   - preview text and diff stat;
   - no secrets.
4. On approval, the executor rechecks the current changed file list. If it differs from the preview-time list, commit is refused.
5. It stages only the approved files using `git add -- <files>`, not `git add --all`.
6. It creates `refs/lingtai-simple/safety/pre-commit-*` before committing.
7. It commits with Wang Runyuan's GitHub noreply identity by default.
8. It never pushes, opens PRs, merges, or claims to do so.

## Validation

Validated before release:

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

Result:

```text
OK LingTai Simple v0.8 self-check passed
```

The regular self-check does not burn external Claude Code tokens and does not approve a commit. It validates that L1/L2 reject without confirmation and that L3 exposes a real confirmation-gated local commit executor.

A destructive smoke test was run in an isolated `/tmp` copy of the repository: create a harmless README change, request L3, approve the queued approval, verify the resulting local commit author is Wang Runyuan, verify the committed file list is exactly the previewed file list, and verify no push/PR/merge happened.

Result:

```text
OK destructive L3 local commit smoke passed
```

## Still not implemented

1. Real PR creation executor using 圆酱 GitHub identity and secret-safe token handling.
2. Real merge executor with explicit WeChat/UI confirmation.
3. Full LingTai runtime/mailbox/skills/memory integration.
4. Independent always-on WeChat runner; current design still uses the existing LingTai WeChat MCP as bridge.
