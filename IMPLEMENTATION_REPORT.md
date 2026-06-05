# LingTai Simple v0.9 Implementation Report

## Summary

v0.9 adds real confirmation-gated **GitHub PR and merge executors** on top of v0.8's Keychain vault, model API, git Time Machine / rollback, WeChat bridge endpoint, Claude Code L1 read-only analysis, L2 local edit, and L3 local commit executor.

The new L4/L5 paths are intentionally bounded:

- L4 can push a reviewed local commit branch and create a real GitHub PR after explicit approval.
- L5 can merge a specified real GitHub PR after explicit approval.
- Neither path runs automatically when the request is created; both first enter the approval queue.
- GitHub login must match `9s5bz2jvd2-lang` to avoid committing or merging with the wrong identity.

## Files changed

- `server.py`
  - Version metadata updated to v0.9.
  - Added GitHub constants: expected login, optional GH config dir, PR body bound.
  - Added safe `gh` helpers and `git push` via temporary `GIT_ASKPASS` calling `gh auth token` without printing the token.
  - Added L4 helpers: `prepare_github_pr_approval()` and `github_pr_apply_real()`.
  - Added L5 helpers: `prepare_github_merge_approval()` and `github_merge_apply_real()`.
  - Approval records now preserve sanitized GitHub repo/base/head/PR metadata.
  - `_apply_approved_action()` now dispatches `code_pr` and `code_merge` to real executors.
  - Health boundaries now list L4/L5 as real confirmation-gated capabilities.
- `README.md`
  - Rewritten for v0.9 with honest real/not-real boundaries.
- `static/app.js`
  - UI copy updated to say L4 PR and L5 merge are real confirmation-gated actions.
- `scripts/self_check.py`
  - Updated to v0.9 and checks that L4 refuses empty/no-ahead PR creation without side effects.
- `data/state.example.json`
  - Demo metadata updated to v0.9.

## L4 PR safety gates

Before queueing:

1. Verify current directory is a git repo.
2. Verify `gh` login and require `9s5bz2jvd2-lang`.
3. Verify current GitHub repo slug.
4. Require a clean worktree.
5. Fetch and verify `origin/<base_branch>`.
6. Require HEAD to be ahead of `origin/<base_branch>`.
7. Sanitize PR title/body and reject secret-like text.
8. Generate a safe branch name.

On approval:

1. Re-check `gh` login and repo slug.
2. Re-check clean worktree.
3. Re-check HEAD matches preview-time commit.
4. Re-check branch/base safety.
5. Refuse to overwrite an existing remote branch unless it already points at the same commit.
6. Push with `GIT_ASKPASS` backed by `gh auth token` (token never printed).
7. Run `gh pr create`.

## L5 merge safety gates

Before queueing:

1. Verify `gh` login and repo slug.
2. Parse PR number or URL from request.
3. Read PR via `gh pr view`.
4. Require state `OPEN` and non-draft.
5. Store base/head/method metadata in the approval.

On approval:

1. Re-check `gh` login and repo slug.
2. Re-read PR.
3. Require state `OPEN` and non-draft.
4. Refuse if base/head changed since preview.
5. Run `gh pr merge <number> --merge --delete-branch` by default.

## Validation plan

- `python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py`
- `python3 scripts/self_check.py`
- High-confidence secret scan.
- Isolated destructive smoke with a local temporary bare GitHub-like remote for branch push behavior.
- Real GitHub creation/merge should be exercised only when an intentional PR target exists and the human expects that side effect.

## Boundaries

- L4 creates PR only; it does not merge.
- L5 merges only an explicitly specified PR.
- Local rollback cannot undo remote GitHub side effects.
- This prototype still relies on the existing LingTai WeChat MCP as the bridge; it does not start a second WeChat poller.
