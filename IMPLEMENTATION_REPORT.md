# LingTai Simple v0.11 Implementation Report

## Summary

v0.11 continues the “真实验收模式” work after v0.10. The key change is that LingTai Simple is no longer only local state for child-spirit orchestration: it now has a real bridge into the LingTai network through the documented internal mailbox outbox contract.

A Simple task can be dispatched to a real agent address under the surrounding `.lingtai/` network. The server writes a real `message.json` to `<sender>/mailbox/outbox/<uuid>/`; LingTai kernel mailman then claims and delivers it to the recipient inbox.

## Changed files

- `server.py`
  - Bumps visible runtime strings to v0.11.
  - Adds `LINGTAI_SIMPLE_NETWORK_DIR` and `LINGTAI_SIMPLE_MAIL_SENDER` support.
  - Adds runtime state fields: `lingtai_runtime`, `lingtai_dispatches`.
  - Adds read-only discovery: `list_lingtai_agents()` / `GET /api/lingtai/agents`.
  - Adds real dispatch: `dispatch_task_to_lingtai()` / `POST /api/lingtai/dispatch`.
  - Adds safe outbox writer following wake-by-mailbox-drop schema.

- `static/index.html`, `static/app.js`
  - Adds “真实 LingTai 派发” large button, card, modal, dispatch history renderer.
  - Agents may show/bind a real `lingtai_address`.
  - Task rows can dispatch to a real LingTai agent.

- `scripts/self_check.py`
  - Updated to v0.11.
  - Creates an isolated fake `.lingtai` network in `/tmp`, starts the server with `LINGTAI_SIMPLE_NETWORK_DIR`, dispatches a task to `worker-one`, and verifies the real outbox `message.json` is written.
  - Does not touch the live `.lingtai` mailbox during this test.

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
OK LingTai Simple v0.11 self-check passed
```

## Boundaries

- v0.11 dispatch is a real internal-mailbox queue into LingTai. It is not a full avatar/runtime lifecycle manager yet.
- Dispatch can wake/occupy a real agent, so UI/API requires `confirm_dispatch=true`.
- The dispatched agent may still need to ask for confirmation before external side effects.
- WeChat still uses the current LingTai WeChat MCP as the only real receive/send bridge; no standalone second poller is started.
- External side effects such as PR/merge/messages cannot be rolled back by git Time Machine.
