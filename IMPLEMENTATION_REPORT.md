# Yuan Nutrition MAS Harness v0.24 Implementation Report

## v0.24 follow-up — Standalone core status

Added `GET /api/standalone/status` as a read-only proof that the cloned lightweight harness can run by itself. It reports core runtime status (`server=running`, Python version, `base_dir`, data/state/static/docs/self-check path presence), standalone capabilities that do not require full LingTai (local GUI/task queue, approvals, `harness_run` state, cost guardrails, git Time Machine when the folder is a git repo, optional Codex/Claude CLI availability), and optional bridge capabilities (LingTai network path if configured/found, controller mailbox dispatch, reply collection, avatar/daemon bridge).

Boundary retained: missing git, LingTai, Codex, or Claude never fails the endpoint. `missing_core` is reserved for actual core blockers and should be empty in this repo. Full LingTai is documented and reported as an optional bridge/enhancement, not a required install for core startup. The endpoint has no automatic external side effects and returns only presence/path/source labels, not secret values.

The GUI now has a small "Standalone Mode / 自运行状态" card and modal that fetches `/api/standalone/status`, shows "Core can run / optional bridge not required", displays core blockers when present, and renders available/unavailable chips for standalone and optional bridge capabilities without redesigning the page.

Self-check now asserts `/api/standalone/status` exists, core startup is OK, `missing_core` is empty, `optional_bridge.requires_full_lingtai` is false for core startup, required local capabilities are available, and the response does not leak fake secret values or high-confidence token patterns.

## v0.24 follow-up — Minimal harness GUI affordance

The existing Harness Run Protocol modal now surfaces `side_effect_reviews[]`, review counts, and `awaiting_side_effect_review` / `pending` / `approved_for_bridge` / `denied` statuses from `GET /api/harness/status`. Each run gets small operator controls only: read-only collect, approval-gated retry creation for attention-needed runs, and local-only manual resolution/update. The GUI preserves the backend safety boundaries: collect only scans existing replies, retry only creates an approval gate, and resolve only updates local audit state without sending WeChat, dispatching mail, approving actions, or calling external tools.

## v0.24 follow-up — External side-effect return gate

Worker/controller replies may now declare `external_side_effects` in `HARNESS_REPLY_JSON` without immediately becoming a WeChat-ready return. When a returned worker result has a WeChat return channel and non-empty `external_side_effects`, `/api/lingtai/collect` records the structured result, marks the worker/run as `awaiting_side_effect_review`, creates a `side_effect_reviews[]` audit row, and queues a `harness_side_effect_return` approval item. Only after that approval is confirmed does the result enter the existing `wechat_outbox` with `ready_for_bridge` status. Approval does not execute any new external action; it only releases the already-collected summary to the no-second-poller WeChat bridge. Denial leaves the run in `needs_human` and keeps return pending.

Self-check now injects a fake controller reply with `external_side_effects` and a WeChat return channel, verifies no outbox item is created before approval, verifies the pending review/approval linkage, then approves the review and verifies a single `ready_for_bridge` outbox item is created.

## v0.24 follow-up — Harness recovery

`POST /api/harness/recover` provides an operator recovery path for watchdog/controller runs without turning the watchdog into an autonomous actor. `action=collect` calls the existing reply collector in read-only mode and appends a `recovery_collect` stage; it does not approve, dispatch, send WeChat, or call external tools. `action=request_retry` is allowed only for runs that need attention (`failed` / `stuck` / `needs_human` or watchdog-stale); it creates a new `worker_dispatch` approval item and appends a `recovery_retry` stage, but it does not write any mailbox until that approval is explicitly approved. A run already awaiting approval rejects duplicate retry requests.

Self-check now injects a stuck harness run, verifies recovery collect leaves dispatch count unchanged, verifies retry creates a worker request + approval with `dispatches_created=0`, and verifies a second retry is rejected while the approval is pending.

## v0.24 follow-up — Manual harness resolution

`POST /api/harness/resolve` lets a local operator manually close or update a `harness_run` that is already `needs_human` / `stuck` / `failed` or has been marked `needs_attention` by the watchdog. It accepts `harness_run_id`, target status, a required `resolution_summary`/`reason`, and optional `next_action`, `artifacts`, and `external_side_effects`; it writes a `manual_resolution` audit object, updates first-class run fields, appends the `manual_resolution` harness stage, and mirrors linked worker/task state where present.

Boundary retained: this endpoint is local state repair only. It does not call external tools, send WeChat, approve actions, or dispatch LingTai mail.

## v0.24 follow-up — Structured result recovery

`POST /api/lingtai/collect` now maps the important fields from `HARNESS_REPLY_JSON` onto first-class audit fields instead of leaving them only inside the raw `structured_result`: `next_action`, `artifacts`, `external_side_effects`, and `has_external_side_effects` are carried into mail result rows, worker requests, harness runs, and the WeChat-origin return text. Artifact and side-effect lists are bounded and redacted recursively before storage.

Boundary retained: collection remains read-only against the LingTai inbox. It records and returns what the controller reported; it does not execute the suggested next action automatically.

## v0.24 follow-up — Harness Watchdog status

`GET /api/harness/status` now includes a read-only watchdog layer for actual harness operations. Recent runs are returned with `last_activity_age_seconds`, `stale_dispatched`, `needs_attention`, and `recommended_action`; the top-level response also summarizes `needs_attention`, `stale_dispatched`, `oldest_active_age_seconds`, and `watchdog.attention_runs`. This helps a nutritionist-facing operator see whether a dispatched/controller run has not been collected for too long, whether an approval has been waiting, or whether a returned run needs human intervention.

Boundary retained: the watchdog is observability only. It does not auto-retry, auto-send, approve, or call external tools.

## v0.24 update — GUI Worker Launcher

Implemented a real, approval-gated worker launcher in the GUI and backend:

- `/api/worker/launcher/status` reports availability for daemon, Codex, Claude, and avatar launch modes.
- `/api/worker/launcher/request` creates `worker_launch` records and approval items.
- Approved daemon launches write a real LingTai controller-mailbox dispatch.
- Approved Codex/Claude launches run local read-only CLI subprocesses and save redacted reports in `data/worker_launches/`.
- Approved avatar launches create a same-network shallow avatar and start `lingtai-agent run`.

Boundary retained: every launch requires approval; Codex/Claude are read-only by default; daemon execution remains delegated to the real LingTai controller rather than the local web server directly owning the daemon tool.



## v0.23 Update — Lightweight LingTai Harness Run Protocol

v0.23 responds to the correction that LingTai Simple is not a shell or GUI wrapper: it is a usable lightweight LingTai harness. Every `/api/task/route` input now creates a `harness_run` that records the protocol `intake -> route -> approval -> dispatch -> collect -> return`. The run links source, return channel, route id, task id, approval id, dispatch id, worker request id, and final collection/return state so a WeChat or GUI request can be audited end-to-end.

Controlled worker dispatch is now harness-aware. Worker requests carry `harness_run_id`; approval records keep `worker_harness_run_id`; approved controller mailbox messages require a `HARNESS_REPLY_JSON` fenced JSON payload with `worker_request_id`, `harness_run_id`, `status`, `summary`, `artifacts`, `next_action`, and `external_side_effects`. `/api/lingtai/collect` parses that structured result, normalizes statuses to `completed / needs_human / stuck / failed`, updates worker/task/harness state, and queues WeChat-origin summaries back into the existing no-second-poller outbox.

New APIs: `GET /api/harness/status` returns harness mode, counts, recent runs, the worker reply contract, and watchdog fields for `needs_attention`, stale dispatched runs, activity age, and recommended actions; `POST /api/harness/recover` gives operators read-only collect and approval-gated retry actions. Self-check now verifies ordinary route harness creation, worker harness linkage, stale-dispatch watchdog detection, recovery collect/retry safety, controller mailbox body contract, structured fake controller reply parsing, and completed worker/harness state.

Honest boundary: Simple still does not directly start daemon/Codex/Claude/avatar workers and still does not run an autonomous WeChat poller. v0.23 is the auditable harness layer: intake, routing, approval, controller dispatch, structured collection, and return.

## v0.22 Update — Scoped Approval Grants

v0.22 adds bounded scoped grants to the Approval Queue. When approving a grantable, non-destructive action, the user can now choose normal approval, `allow-once`, or `allow-for-task`. Matching future approval items are written with status `grant自动确认`, linked to `grant_id`, and audited through `used_by`, `remaining_uses`, expiry timestamps, and used/expired status. Destructive/high-impact actions such as rollback, commit, PR, merge, LingTai lifecycle signals, and avatar spawn/retire explicitly refuse scoped grants and still require per-item confirmation.

Self-check now covers: creating an allow-once grant from a `sensitive_task`, automatic confirmation of the next matching approval, grant exhaustion/audit fields, and refusal of scoped grants for `code_merge`. The UI exposes “确认并允许下一次同类” and “确认并允许本任务同类” buttons when the approval item is grantable. The WeChat bridge accepts `确认下次 <approval_id>` and `确认本任务 <approval_id>` command forms.

Honest boundary: scoped grants are intentionally narrow. They reduce repeated confirmations for bounded, repeatable work, but they do not bypass destructive actions or external irreversible operations.

## v0.21 Update — Controlled Worker Dispatch Aggregation

v0.21 added an approval-gated controlled worker dispatch path. `POST /api/task/route` turns daemon / Codex / Claude / avatar-style requests into local `worker_requests[]` plus a `worker_dispatch` approval. After approval, Simple writes a real LingTai internal mailbox message to a controller agent (default `mimo-2-5-pro`). `POST /api/lingtai/collect` can match controller replies by `worker_request_id`, update local worker/task/dispatch state, and queue a WeChat outbox summary for WeChat-origin requests under the existing `no_second_poller` bridge contract.

Honest boundary: Simple does not directly start daemon/Codex/Claude/avatar workers and does not run a second WeChat poller; it coordinates through controller mailbox and explicit approvals.

## v0.20 Update — Budget / Cost Guardrail Panel

v0.20 added a local budget and cost guardrail panel. It exposes `/api/cost/status` and `/api/cost/policy`, adds `cost_policy` to `/api/catalog`, preflights real model calls and Claude Code L1/L2 runs against local caps, creates `budget_override` approval items when a run would exceed policy, and records successful model/Claude Code executions in a local `cost_ledger`. The UI has a budget/cost big button, dashboard card, and policy modal.

Honest boundary: this is a local estimate and confirmation guardrail, not a connection to provider billing or account balances. The price table is intentionally conservative and must be calibrated by the user for the exact provider/model.

New / changed endpoints:

- `POST /api/approval/approve` — supports optional `grant_scope=once|task` for grantable non-destructive approvals; destructive actions reject scoped grants.
- `POST /api/task/route` — classifies one sentence into local task, multi-agent orchestration, insight, soul flow, shougong, real LingTai mailbox dispatch, reply collection, Claude/Codex handoff, or daemon plan.
- `POST /api/wechat/bridge/pending` — returns `ready_for_bridge` WeChat outbox items with `runner_contract=no_second_poller`.
- `/api/wechat/bridge/incoming` — default non-command messages now go through the unified router and store `route_id` in the inbound item.

Validation added:

- `scripts/self_check.py` now verifies scoped approval grants, ordinary router tasks, router-triggered fake-network LingTai mailbox dispatch, WeChat default-route `route_id`, pending outbox retrieval, and mark-sent behavior.
- Expected output: `OK Yuan Nutrition MAS Harness v0.24 self-check passed`.

Honest boundary:

- v0.23 is still not an autonomous standalone WeChat poller. It is the local harness/routing/contract layer for the existing LingTai WeChat MCP bridge.
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
- Expected output: `OK Yuan Nutrition MAS Harness v0.24 self-check passed`.


## v0.17.1 Download-and-run packaging

Added portable GitHub clone/run support so the project is not tied to the original local absolute path:

- `run.sh` starts the local server from the repository root and opens `http://127.0.0.1:<port>/` when possible.
- `QUICKSTART.md` documents clone, ZIP download, startup, self-check, demo state, real-integration boundaries, and safety rules.
- README run instructions now use `git clone` + `./run.sh` instead of the original local development path.
- Health check now treats git/Claude/GitHub/LingTai network as optional integration checks, so a ZIP download without `.git` can still start and report core UI health.

This does not make unavailable integrations magically active: model calls, Claude Code, GitHub PR/merge, real WeChat bridge, and real LingTai mailbox dispatch still require the corresponding local tools, credentials, or existing LingTai runtime wiring. The self-check remains the primary downloadable-run validation gate.

## Summary

Yuan Nutrition MAS Harness is a nutritionist-friendly Multi-Agent System (MAS) harness developed by Wang Runyuan on top of [LingTai](https://github.com/Lingtai-AI/lingtai). It keeps LingTai's orchestration, approval, rollback, mailbox, and worker-handoff ideas, but packages them for nutrition-AI workflows and nutrition professionals.


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
OK Yuan Nutrition MAS Harness v0.24 self-check passed
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

## v0.23 架构验收矩阵

新增：

- `ARCHITECTURE_ACCEPTANCE_MATRIX.md`：把 `../ARCHITECTURE_EXPERT_DISCUSSION.md` 的 WeChat Gate、Simple Frontend、Task Router、Agent Manager、Model/API Registry、Secret Vault、Approval Queue、Worker Pool、Memory/Skills/Molt、Rollback，以及“GitHub 下载即可运行”逐项映射为 `Done / Partial / Missing`。
- `GET /api/architecture/status`：本地只读 API，返回机器可读验收状态、证据、缺口、测试命令与下一批优先实现项。
- 前端新增 **📋 架构验收表** 大按钮和 modal。

诚实边界：v0.22 不是宣称所有架构要求已完成，而是在 v0.21 worker dispatch 与 v0.20 成本闸基础上补上 Approval Queue 的 scoped grants。下一步仍可继续深化 controller 侧标准执行协议、日志/截图/报告外发确认、以及成本估算与真实供应商账单/余额（如可用）的校准。


## v0.17 Secret Vault health scan
- `/api/health` 和 `/api/secret/scan` 现在会结构化扫描 state/example/.env/.secrets JSON 中的高置信明文 key 风险。
- 扫描结果只返回位置、字段、严重级别和迁移建议；不会回显任何疑似 key/token 值。
- `scripts/self_check.py` 会创建临时风险文件验证可检测性，再删除并确认健康检查恢复 OK。

## v0.22 Secret Vault restricted fallback

- Keychain 仍为第一优先级；API/state/log/health scan 均不回显 secret value。
- 新增只读 env fallback：`LINGTAI_SIMPLE_API_KEY_<PROVIDER>`，例如 `LINGTAI_SIMPLE_API_KEY_DEEPSEEK`。
- 新增显式 opt-in `.secrets/providers/<provider>.key` fallback：只有用户勾选/传入 `allow_secret_fallback=true` 且 Keychain 写入失败或被禁用时才写入；目录必须 0700，文件必须 0600；拒绝 symlink/不安全权限。
- `/api/secret/scan` 现在报告 fallback 文件位置、mode 与权限风险，但不读取、不返回 key 内容。
- 剩余缺口：预算/成本面板尚未与 provider secret 状态联动。
