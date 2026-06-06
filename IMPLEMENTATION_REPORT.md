# LingTai Simple v0.13 Implementation Report

## Summary

v0.13 continues the “真实验收模式” work after v0.11. v0.11 wrote real internal-mailbox dispatches into the LingTai network; v0.13 closes the first feedback loop: Simple can now collect real internal-mail replies from a configured reply inbox and mark the corresponding dispatch/task as replied.

v0.13 also adds a confirmation-gated lifecycle surface for existing real LingTai agents. It does not execute destructive lifecycle operations immediately. It creates a preview item in the approval queue, then applies the real `.sleep` / `.suspend` / `.interrupt` / `.clear` signal or CPR process launch only after approval.

## Changed files

- `server.py`
  - Bumps visible runtime strings to v0.13.
  - Adds `LINGTAI_SIMPLE_REPLY_INBOX`, `LINGTAI_SIMPLE_AGENT_CMD`, and heartbeat freshness configuration.
  - Extends `lingtai_runtime` with `reply_inbox`.
  - Adds `lingtai_mail_results` and `lingtai_lifecycle_events` state arrays.
  - Extends real agent discovery with heartbeat freshness / alive information.
  - Adds `collect_lingtai_mail_results()` and route `POST /api/lingtai/collect`.
  - Matches incoming mailbox replies to prior dispatches by original mailbox id, sender, or subject, then updates dispatch/task state.
  - Adds lifecycle request route `POST /api/lingtai/lifecycle/request`.
  - Adds approval-preview support for `lingtai_lifecycle` actions.
  - Applies approved `lull`, `suspend`, `interrupt`, `clear`, and `cpr` actions through real signal files / detached `lingtai-agent run`.

- `static/app.js`
  - Updates frontend strings to v0.13.
  - Renders recovered real-agent replies and lifecycle event history.
  - Adds buttons for “回收真实 agent 回复” and “生命周期动作”.
  - Adds lifecycle modal and API calls for confirmation-gated lifecycle requests.

- `static/index.html`
  - Updates the visible milestone text from v0.11 dispatch-only to v0.13 dispatch + reply collection + lifecycle gate.

- `scripts/self_check.py`
  - Updated to v0.13.
  - Creates an isolated fake `.lingtai` network in `/tmp`.
  - Verifies real outbox `message.json` dispatch without touching live mailboxes.
  - Places a fake matching reply into the fake reply inbox, calls `/api/lingtai/collect`, and verifies the dispatch becomes `reply_received`.
  - Verifies lifecycle requests create a `lingtai_lifecycle` approval without executing real signals during self-check.

- `README.md`, `IMPLEMENTATION_REPORT.md`
  - Documents the new real/not-real boundary.

## Validation

Run:

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
node --check static/app.js
python3 scripts/self_check.py
```

Observed result:

```text
OK LingTai Simple v0.13 self-check passed
```

## Boundaries

- Reply collection is read-only over the configured reply inbox. It does not delete, move, or mark LingTai mailbox files as read.
- Lifecycle actions affect real agents only after approval. `clear` can wipe an agent context; CPR can start a process. Both are confirmation-gated.
- v0.13 is still not a full avatar manager: no real spawn/delete UI, no nirvana, no arbitrary filesystem deletion.
- Dispatch/reply/lifecycle actions can wake, occupy, sleep, suspend, interrupt, clear, or revive real agents. They must be used deliberately.
- WeChat still uses the current LingTai WeChat MCP as the only real receive/send bridge; no standalone second poller is started.
- External side effects such as PR/merge/messages cannot be rolled back by git Time Machine.
