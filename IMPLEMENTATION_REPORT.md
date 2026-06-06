# LingTai Simple v0.20 Implementation Report


## v0.20 Update — Budget / Cost Guardrail Panel

v0.20 adds a local budget and cost guardrail panel. It exposes `/api/cost/status` and `/api/cost/policy`, adds `cost_policy` to `/api/catalog`, preflights real model calls and Claude Code L1/L2 runs against local caps, creates `budget_override` approval items when a run would exceed policy, and records successful model/Claude Code executions in a local `cost_ledger`. The UI now has a budget/cost big button, dashboard card, and policy modal.

Honest boundary: this is a local estimate and confirmation guardrail, not a connection to provider billing or account balances. The price table is intentionally conservative and must be calibrated by the user for the exact provider/model.

New / changed endpoints:

- `POST /api/task/route` — classifies one sentence into local task, multi-agent orchestration, insight, soul flow, shougong, real LingTai mailbox dispatch, reply collection, Claude/Codex handoff, or daemon plan.
- `POST /api/wechat/bridge/pending` — returns `ready_for_bridge` WeChat outbox items with `runner_contract=no_second_poller`.
- `/api/wechat/bridge/incoming` — default non-command messages now go through the unified router and store `route_id` in the inbound item.

Validation added:

- `scripts/self_check.py` now verifies ordinary router tasks, router-triggered fake-network LingTai mailbox dispatch, WeChat default-route `route_id`, pending outbox retrieval, and mark-sent behavior.
- Expected output: `OK LingTai Simple v0.20 self-check passed`.

Honest boundary:

- v0.20 is still not an autonomous standalone WeChat poller. It is the local routing/contract layer for the existing LingTai WeChat MCP bridge.
- Code-worker and daemon routes intentionally record handoff/plan instead of bypassing the existing Claude Code/daemon confirmation surfaces.

## v0.17 Update — real LingTai memory / skill index

v0.17 adds a read-only durable-store index for the current real LingTai agent. Simple can now show what the agent remembers and what reusable skills it has, without exposing secrets, mailboxes, logs, or arbitrary filesystem paths.

New endpoints:

- `GET /api/lingtai/memory` — scans whitelisted durable stores and returns counts plus metadata for pad, character, current projects, knowledge entries, custom/shared skills, and recent molt summaries.
- `POST /api/lingtai/memory/scan` — records a scan summary into Simple state for the GUI runtime card.
- `POST /api/lingtai/memory/read` — reads only allowed text files under the whitelisted durable-store roots, with truncation and hidden-file/path traversal rejection.

New UI:

- Adds a “记忆 / 技能索引” big button.
- Adds a runtime card showing latest pad / knowledge / skill / molt-summary scan counts.
- Adds modal rows that can open whitelisted memory/skill files in a bounded preview.

Safety boundary:

- Read-only; no writes to pad, knowledge, skills, or summaries.
- Does not read `.secrets`, mailbox contents, logs, hidden files, or arbitrary paths.
- Does not automatically send durable-store content to external model APIs.

Validation added:

- `scripts/self_check.py` now builds an isolated fake LingTai agent with pad, knowledge, custom skill, shared skill, summary, and `.secrets`; verifies memory scan/read works and `.secrets` read is rejected.
- Expected output: `OK LingTai Simple v0.20 self-check passed`.


## v0.17.1 Download-and-run packaging

Added portable GitHub clone/run support so the project is not tied to the original local absolute path:

- `run.sh` starts the local server from the repository root and opens `http://127.0.0.1:<port>/` when possible.
- `QUICKSTART.md` documents clone, ZIP download, startup, self-check, demo state, real-integration boundaries, and safety rules.
- README run instructions now use `git clone` + `./run.sh` instead of the original local development path.
- Health check now treats git/Claude/GitHub/LingTai network as optional integration checks, so a ZIP download without `.git` can still start and report core UI health.

This does not make unavailable integrations magically active: model calls, Claude Code, GitHub PR/merge, real WeChat bridge, and real LingTai mailbox dispatch still require the corresponding local tools, credentials, or existing LingTai runtime wiring. The self-check remains the primary downloadable-run validation gate.

## Summary

 v0.14 adds safe avatar management on top of v0.13: binding existing real agents into Simple cards, and confirmation-gated retire/unbind semantics that never delete real agent directories or call nirvana.

v0.14 continues the “真实验收模式” work after v0.11. v0.11 wrote real internal-mailbox dispatches into the LingTai network; v0.14 closes the first feedback loop: Simple can now collect real internal-mail replies from a configured reply inbox and mark the corresponding dispatch/task as replied.

v0.14 also adds a confirmation-gated lifecycle surface for existing real LingTai agents. It does not execute destructive lifecycle operations immediately. It creates a preview item in the approval queue, then applies the real `.sleep` / `.suspend` / `.interrupt` / `.clear` signal or CPR process launch only after approval.

## Changed files

- `server.py`
  - Bumps visible runtime strings to v0.14.
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
  - Updates frontend strings to v0.14.
  - Renders recovered real-agent replies and lifecycle event history.
  - Adds buttons for “回收真实 agent 回复” and “生命周期动作”.
  - Adds lifecycle modal and API calls for confirmation-gated lifecycle requests.

- `static/index.html`
  - Updates the visible milestone text from v0.11 dispatch-only to v0.14 dispatch + reply collection + lifecycle gate.

- `scripts/self_check.py`
  - Updated to v0.14.
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
OK LingTai Simple v0.20 self-check passed
```

## Boundaries

- Reply collection is read-only over the configured reply inbox. It does not delete, move, or mark LingTai mailbox files as read.
- Lifecycle actions affect real agents only after approval. `clear` can wipe an agent context; CPR can start a process. Both are confirmation-gated.
- v0.14 is still not a full avatar manager: no real spawn/delete UI, no nirvana, no arbitrary filesystem deletion.
- Dispatch/reply/lifecycle actions can wake, occupy, sleep, suspend, interrupt, clear, or revive real agents. They must be used deliberately.
- WeChat still uses the current LingTai WeChat MCP as the only real receive/send bridge; no standalone second poller is started.
- External side effects such as PR/merge/messages cannot be rolled back by git Time Machine.


## v0.14 Safe Avatar Management

- `POST /api/lingtai/avatar/bind` binds an existing real `.lingtai/<address>` agent to a Simple local card. This is local-state only: no process start, no deletion.
- `POST /api/lingtai/avatar/retire` queues a confirmation item for retire/unbind. Approval marks local bound cards retired and optionally writes `.sleep` or `.suspend` if requested and heartbeat is fresh.
- Bound-card delete now routes to `lingtai_avatar_retire`; raw filesystem deletion remains intentionally absent.
- Self-check validates bind, delete-to-retire routing, approval execution, and confirms the fake real agent directory remains present.

## v0.20 架构验收矩阵

新增：

- `ARCHITECTURE_ACCEPTANCE_MATRIX.md`：把 `../ARCHITECTURE_EXPERT_DISCUSSION.md` 的 WeChat Gate、Simple Frontend、Task Router、Agent Manager、Model/API Registry、Secret Vault、Approval Queue、Worker Pool、Memory/Skills/Molt、Rollback，以及“GitHub 下载即可运行”逐项映射为 `Done / Partial / Missing`。
- `GET /api/architecture/status`：本地只读 API，返回机器可读验收状态、证据、缺口、测试命令与下一批优先实现项。
- 前端新增 **📋 架构验收表** 大按钮和 modal。

诚实边界：v0.20 不是宣称所有架构要求已完成，而是在 v0.17 验收矩阵基础上补上统一 Task Router 与 WeChat pending outbox 合同；下一步优先继续把 Task Router 扩展到受控 daemon/Codex/real avatar 调度与结果汇总，并把成本估算与真实供应商账单/余额（如可用）进一步校准。


## v0.17 Secret Vault health scan
- `/api/health` 和 `/api/secret/scan` 现在会结构化扫描 state/example/.env/.secrets JSON 中的高置信明文 key 风险。
- 扫描结果只返回位置、字段、严重级别和迁移建议；不会回显任何疑似 key/token 值。
- `scripts/self_check.py` 会创建临时风险文件验证可检测性，再删除并确认健康检查恢复 OK。

## v0.20 Secret Vault restricted fallback

- Keychain 仍为第一优先级；API/state/log/health scan 均不回显 secret value。
- 新增只读 env fallback：`LINGTAI_SIMPLE_API_KEY_<PROVIDER>`，例如 `LINGTAI_SIMPLE_API_KEY_DEEPSEEK`。
- 新增显式 opt-in `.secrets/providers/<provider>.key` fallback：只有用户勾选/传入 `allow_secret_fallback=true` 且 Keychain 写入失败或被禁用时才写入；目录必须 0700，文件必须 0600；拒绝 symlink/不安全权限。
- `/api/secret/scan` 现在报告 fallback 文件位置、mode 与权限风险，但不读取、不返回 key 内容。
- 剩余缺口：预算/成本面板尚未与 provider secret 状态联动。
