# LingTai Simple v0.6 Implementation Report

## Summary

v0.6 adds a real **Claude Code L1 read-only analysis worker** on top of v0.5's real Keychain vault, model API test, git Time Machine / rollback, and WeChat bridge endpoint.

It is intentionally narrow: L1 can call the local `claude` CLI for read-only analysis only after explicit cost confirmation. L2+ editing, commit, PR, and merge remain not connected and are honestly routed to the confirmation queue as local records only.

## What changed

### Backend (`server.py`)

- Version metadata updated to v0.6.
- Added `cc_runs` state and `data/cc_runs/` report output.
- Added Claude Code availability to health check.
- Added `POST /api/cc/request` special handler:
  - `level=1` + `confirm_cost=true` starts a real Claude Code read-only run.
  - `level=1` without confirmation is rejected before any external call.
  - task descriptions that look like API keys/tokens are rejected.
  - `level>=2` goes to confirmation queue and is marked as no real executor yet.
- Real Claude Code command is constrained:
  - `claude --print`
  - `--permission-mode plan`
  - `--tools Read,Grep,Glob`
  - `--disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch`
  - `--max-budget-usd` defaults to `0.50` via `LINGTAI_SIMPLE_CC_MAX_BUDGET_USD`.
  - `--no-session-persistence`
- Output is redacted, written to `data/cc_runs/<run_id>.md`, and surfaced in public state.

### Frontend (`static/index.html`, `static/app.js`)

- Updated to v0.6 wording.
- WeChat button is no longer greyed as fake: it opens the bridge-test modal, while clearly saying real operation still uses current LingTai WeChat MCP as the only bridge.
- Claude Code button is enabled for L1 read-only analysis.
- The Claude modal now includes a cost confirmation checkbox.
- Added Claude Code run history / preview section.
- UI wording states that edit/commit/PR/merge are not connected yet.

### Self-check (`scripts/self_check.py`)

- Updated to v0.6.
- Confirms `/api/health` reports v0.6 and Claude CLI availability field exists.
- Confirms model API still refuses to call without cost confirmation.
- Confirms Claude Code L1 refuses to call without cost confirmation.
- Confirms Claude Code L2+ queues an approval with `real_executor=false`.
- Confirms WeChat bridge status/outbox flow still works.
- Confirms fake API key never appears in `state.json`.

### Git ignore

- Added `data/cc_runs/` so generated Claude Code reports are local runtime artifacts, not committed.

## Validation

```text
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

Result:

```text
OK LingTai Simple v0.6 self-check passed
```

High-confidence secret scan should be run before push; no real API key or token is expected in tracked files.

## Honest boundaries

- L1 read-only analysis is a real Claude Code call, but self-check does not burn tokens by default.
- L1 is still an external model call and may cost money; UI/API require explicit confirmation.
- L1 is constrained by CLI flags, but the strongest guarantee comes from keeping it read-only and reviewing output; it is not a sandbox for untrusted code execution.
- L2+ editing/commit/PR/merge is not connected yet.
- WeChat is bridge-based; this service does not run a second poller or store WeChat credentials.
- Rollback only affects this repository's git-tracked/unignored files and cannot undo external side effects.

## Next implementation slice

1. Controlled Claude Code L2 local-edit worker in an isolated worktree.
2. Mandatory diff preview + secret scan + test summary before any commit.
3. Commit/PR/merge confirmation gates using Runyuan's GitHub identity.
4. Persistent WeChat bridge runner/skill so current LingTai automatically relays messages to LingTai Simple.
