# Yuan Nutrition MAS Harness v0.24

> **Temporary public demonstration notice**<br>
> 目前为研发中临时开放展示，未经许可不得复制、商用、再分发或作为衍生系统发布。<br>
> This repository is temporarily public for demonstration while under development. Without prior permission, copying, commercial use, redistribution, or release as a derivative system is not allowed.

**Yuan Nutrition MAS Harness** is a nutritionist-friendly Multi-Agent System (MAS) harness developed by Wang Runyuan, inspired by [LingTai](https://github.com/Lingtai-AI/lingtai) and able to bridge to it when configured. The lightweight harness core is standalone: after clone/download it runs with Python stdlib plus the included vanilla HTML/CSS/JS UI. You do **not** need to install full LingTai to start the local app, task queue, approval gates, harness run state, budget guardrails, docs, or self-check.

This is not a shell or a button-only GUI. It is a runnable **lightweight harness**: WeChat/GUI input enters a local `harness_run`, then follows the auditable protocol `intake → route → approval → dispatch → collect → return`. v0.24 builds on optional LingTai bridge entry points, a standalone HTTP connector for WeChat/external-channel inbound, read-only memory/skill indexes when a LingTai agent directory is configured, Secret Vault restricted fallback, unified Task Router, budget/cost panel, controlled worker dispatch, scoped approval grants, the **GUI Worker Launcher**, a read-only Harness Watchdog, and local-only manual harness resolution. Full LingTai capabilities are optional enhancements: daemon requests can be written to a configured LingTai controller mailbox, replies can be collected from a configured inbox, and avatar/daemon bridge features require a real LingTai network. Codex/Claude are also optional local CLI workers. The watchdog adds `needs_attention`, `stale_dispatched`, `last_activity_age_seconds`, and recommended actions to `/api/harness/status` so stuck/long-uncollected runs are visible without changing external state; `/api/harness/resolve` lets an operator close or mark those runs locally without sending, approving, or dispatching anything; `/api/harness/recover` adds a bounded recovery path: `collect` only scans the reply inbox, while `request_retry` creates a fresh approval gate and never auto-resends. If a controller reply declares `external_side_effects`, the WeChat return is held behind a `harness_side_effect_return` confirmation gate before it can enter `wechat_outbox`.

Standalone proof endpoint:

```bash
curl http://127.0.0.1:8765/api/standalone/status
curl http://127.0.0.1:8765/api/connectors/status
```

It reports core runtime status, local standalone capabilities, standalone connector status, optional bridge capabilities, `missing_core`, and recommended actions. Missing git, Codex, Claude, or LingTai are reported as unavailable optional features rather than core startup failures.

Standalone WeChat/external-channel connector: full LingTai is **not** required for local inbound. `POST /api/connectors/wechat/incoming` accepts `text`, `user_id`, `message_id`, and optional `sender`, routes through the same harness logic, and creates a standalone `wechat_outbox` item. `POST /api/connectors/wechat/pending` and `POST /api/connectors/wechat/mark_sent` are endpoint-driven; no poller or sender loop is started. Real outbound sending still needs an external WeChat provider/API/webhook credential such as `YUAN_WECHAT_OUTBOUND_URL` or `LINGTAI_SIMPLE_WECHAT_OUTBOUND_URL`; status only returns configured/source labels and safe hostname, never the secret URL. The existing `/api/wechat/bridge/*` LingTai MCP bridge endpoints remain supported.


## v0.24: GUI Worker Launcher

The GUI can create optional worker-launch requests for four worker bodies, all behind the approval queue:

- **daemon**: optional LingTai bridge worker; writes a real LingTai controller-mailbox dispatch when `LINGTAI_SIMPLE_NETWORK_DIR` is configured. The controller agent is responsible for using the daemon tool and returning `HARNESS_REPLY_JSON`.
- **Codex**: optional local CLI worker; starts local `codex exec --sandbox read-only` and writes a redacted Markdown report under `data/worker_launches/` if the CLI is installed.
- **Claude**: optional local CLI worker; starts local `claude --print --permission-mode plan` with only `Read,Grep,Glob` allowed and `Bash/Edit/Write` disallowed if the CLI is installed.
- **avatar**: optional LingTai bridge worker; creates a real same-network shallow avatar and starts `lingtai-agent run` after approval when a LingTai network and agent command are configured.

Honest boundary: the app core is local-first, standalone, and approval-gated. Codex/Claude may incur model cost when used; avatar creates local `.lingtai` agent files when the optional bridge is configured; daemon is not executed directly by the web process but by the real LingTai controller workflow.

## Public demonstration status

- **Repository**: temporarily public source repository at <https://github.com/9s5bz2jvd2-lang/yuan-nutrition-mas-harness>
- **License**: [Temporary Public Demonstration License](LICENSE), Copyright (c) 2026 Wang Runyuan. All rights reserved.
- **Security and safety policy**: see [SECURITY.md](SECURITY.md)
- **Roadmap**: see [ROADMAP.md](ROADMAP.md)

This project is local-first. Do not expose the local server directly to the public internet, do not commit real credentials, and keep high-impact actions confirmation-gated. For nutrition/medical content, the harness supports workflow and evidence review; it does not replace professional judgment, diagnosis, or treatment.

## v0.23：Lightweight LingTai Harness（不是壳）

本地可查 harness 状态：

```bash
curl http://127.0.0.1:8765/api/harness/status
```

真实新增点：

- `/api/task/route` 每次调用都会创建 `harness_runs[]`，协议固定为 `intake -> route -> approval -> dispatch -> collect -> return`。
- WeChat / GUI 来源会记录 `source`、`return_channel`、`route_id`、`task_id`、`approval_id`、`worker_request_id` 等关联，便于追踪“输入到底走到了哪里”。
- daemon / 分神 / Codex / Claude / avatar 类请求先进入 `worker_dispatch` 确认闸；批准后写 controller 内部邮箱。
- controller 邮件正文要求回信包含 `HARNESS_REPLY_JSON` fenced JSON，字段为 `worker_request_id / harness_run_id / status / summary / artifacts / next_action / external_side_effects`。
- `/api/lingtai/collect` 会解析结构化回信，把 `worker_request`、`harness_run`、`task` 更新为 `completed / needs_human / stuck / failed` 等状态，并显式沉淀 `summary / artifacts / next_action / external_side_effects`；若有 WeChat return channel 且 `external_side_effects` 非空，会先进入 `harness_side_effect_return` 确认门，批准后才进入 WeChat outbox。

诚实边界：v0.24 已能从 GUI 真正启动 Codex/Claude 只读本机子进程和真实 avatar；daemon 仍由 Simple 写入真实 controller mailbox 后交给 controller 使用 daemon 工具执行。它仍不启动第二个微信 poller，也不绕过确认队列。

## v0.23：架构验收表（不许糊弄）

圆酱要求“架构讨论稿里的每一项都要真实实现、可实际跑通”。v0.23 继续用 `ARCHITECTURE_ACCEPTANCE_MATRIX.md` 与本地 API 暴露真实验收状态：

```bash
curl http://127.0.0.1:8765/api/architecture/status
```

UI 里点击 **📋 架构验收表** 可查看每一项要求的 `Done / Partial / Missing`、已跑通证据、缺口和测试命令。原则是：**未真实跑通，不写已完成**。

## v0.23 新增/保留真实接入

### -5. Harness Run Protocol（v0.23 新增）

- 每条微信/GUI 输入生成 `harness_run`，把 intake、route、approval、dispatch、collect、return 串成一条可审计链。
- `/api/harness/status` 返回 harness 模式、计数、最近 runs、worker 回信合同，以及只读 watchdog 字段：`needs_attention`、`stale_dispatched`、`last_activity_age_seconds`、`recommended_action`。
- GUI 的 Harness Run Protocol 弹窗显示这些 run 状态、`side_effect_reviews[]` 与待确认计数，并只提供轻量操作：只读回收、创建 retry 确认门、人工本地 resolution。
- `POST /api/harness/resolve` 可人工把 watchdog/controller 标记的 `completed / needs_human / stuck / failed` run 写入本地 `manual_resolution`，同步 linked worker/task 审计字段；它不调用外部工具、不发微信、不批准、不派发邮箱。
- `POST /api/harness/recover` 支持两种恢复动作：`collect` 只读扫描 reply inbox 并记录 `recovery_collect`；`request_retry` 只创建新的 `worker_dispatch` 确认门并记录 `recovery_retry`，在批准前不会重发邮箱或调用外部工具。
- worker controller 回信从自由文本升级为 `HARNESS_REPLY_JSON` 结构化结果，回收时自动写入 `structured_result`。
- WeChat 来源的普通 worker 结果仍进入 `wechat_outbox`，由现有 WeChat MCP 原路回发；若 worker 声明 `external_side_effects`，结果先进入 `side_effect_reviews[]` 与 `harness_side_effect_return` 确认项，确认前不会变成 `ready_for_bridge`。

### -4. 确认队列 scoped grants（v0.22 已接入，v0.23 保留）

- 对 `wechat_send`、`email_send`、`telegram_send`、`high_cost_api`、`sensitive_task`、`budget_override`、`worker_dispatch` 这类可重复且非破坏性的动作，确认时可选择：
  - **确认/执行**：只批准当前这一项。
  - **确认并允许下一次同类**：创建 30 分钟内有效、最多自动使用 1 次的 once grant。
  - **确认并允许本任务同类**：创建 120 分钟内有效、同一 `task_id` 下最多自动使用 5 次的 task grant。
- 后续匹配 grant 的确认项会以 `grant自动确认` 状态写入 approvals，并记录 `grant_id`、`used_by`、`remaining_uses`、过期/用尽状态，便于审计。
- WeChat 桥接也支持 `确认下次 <approval_id>` / `确认本任务 <approval_id>`（以及英文 `approve-once` / `approve-task`）来创建对应授权。
- 边界：`rollback_apply`、`code_commit`、`code_pr`、`code_merge`、`lingtai_lifecycle`、`lingtai_avatar_spawn`、`lingtai_avatar_retire` 等仍必须逐项确认；scoped grants 不会绕过这些高影响动作。

### -3. 受控 worker 调度（v0.21 接入，v0.23 结构化）

- `/api/task/route` 识别 daemon / 分神 / Codex / Claude / avatar 类请求后，会创建 `worker_requests[]`、本地任务和 `worker_dispatch` 确认项。
- 批准确认项后，Simple 会写入真实 LingTai 内部邮箱，把请求交给 controller agent（默认 `mimo-2-5-pro`，可用 `LINGTAI_SIMPLE_WORKER_CONTROLLER` 覆盖）。
- v0.23 起，调度信带 `harness_run_id`，并强制要求 controller 用 `HARNESS_REPLY_JSON` 回信。
- `/api/lingtai/collect` 可按 `worker_request_id` / `harness_run_id` 回收 controller 回信，更新 worker request / dispatch / task / harness run，并把 `next_action`、`artifacts`、`external_side_effects` 单独落到可审计字段；若请求来自 WeChat 且无外部副作用声明，则进入 `wechat_outbox`，若声明了 `external_side_effects`，则先等待本地确认后才由现有 WeChat MCP 原路回复。
- 边界：Simple 自身不直接启动第二个微信 poller，也不绕过 daemon/Codex/Claude/avatar 的既有安全纪律；这是“确认闸 + controller mailbox + 结构化回信汇总”的受控链路。

### -2. 预算/成本面板（v0.20 已接入，v0.23 保留）

- `GET /api/cost/status`：读取本地估算成本状态、今日累计、provider/kind 分布、warnings 与最近 ledger。
- `POST /api/cost/policy`：调整本地预算策略，包括 daily cap、provider 单次 cap、任务 cap、Claude Code run cap、长跑阈值、是否启用越线确认，以及是否清空本地 ledger。
- `/api/model/test` 在 `confirm_cost=true` 后仍会先估算成本；如果超过策略上限，会先生成 `budget_override` 确认项，不会直接发起真实网络调用。确认后只放行 30 分钟，需用户重新执行原动作。
- Claude Code L1/L2 也走预算预检，按 `CC_MAX_BUDGET_USD` 做本地预留估算；执行完成后写入 `cost_ledger`。
- UI 有“预算/成本面板”大按钮、成本卡片与策略 modal。

边界：这是本地 guardrail / 估算账本，不是供应商真实账单、余额查询或自动扣费审计；默认价格表只用于保守提醒，必须按实际 provider/model 校准。

### -1. 统一 Task Router / WeChat runner contract（v0.18 接入，v0.23 升级为 harness 入口）

- `POST /api/task/route`：把一句话分类为普通本地任务、多 agent、洞察、心流、收功、真实 LingTai mailbox 派发、结果回收、Claude/Codex handoff 或 daemon 计划，并创建 harness run。
- `POST /api/wechat/bridge/pending`：返回 `ready_for_bridge` 的微信 outbox 项，供当前 LingTai WeChat MCP 桥接者发送；runner contract 固定为 `no_second_poller`。
- `GET /api/connectors/status`：只读返回 standalone connector 状态；`requires_full_lingtai=false`，不回显 outbound webhook URL。
- `POST /api/connectors/wechat/incoming`：无需完整 LingTai 的 standalone HTTP inbound；同样写入 `wechat_inbox`、走统一路由、生成 standalone outbox。
- `GET|POST /api/connectors/wechat/pending` 与 `POST /api/connectors/wechat/mark_sent`：仅处理 standalone connector 的 pending/sent 标记，不自动外发。
- `/api/wechat/bridge/incoming` 的默认普通消息走统一 Task Router / Harness，并在 inbox 记录 `route_id` 与 `harness_run_id`，便于追踪“微信一句话 → 路由 → 确认/派发/回收/回传”的路径。
- `confirm_dispatch=true` 时，router 可在 fake/真实 `.lingtai` 网络中写入真实内部邮箱 outbox；未确认时只创建本地任务并提示需要确认，避免误唤醒/占用真实 agent。

边界：v0.23 不是独立微信 poller，也不会由本地 Simple 服务直接启动 daemon 或绕过 Claude Code/费用确认；代码苦力和 daemon 类任务真实执行仍走对应受控入口。

### 0. LingTai 记忆 / 技能只读索引（v0.17 新增）

- `GET /api/lingtai/memory`：只读扫描当前真实 agent 的 durable stores，返回 pad、lingtai character、CURRENT_PROJECTS、knowledge、custom skills、shared skills、最近 molt summaries 的索引和计数。
- `POST /api/lingtai/memory/scan`：把一次扫描摘要写入 Simple 本地状态，便于 GUI 展示最近索引结果。
- `POST /api/lingtai/memory/read`：只允许读取白名单根目录下的文本文件，并限制输出长度；拒绝 `.secrets`、mailbox、logs、隐藏文件和任意路径穿越。
- GUI 新增“记忆 / 技能索引”大按钮与运行时卡片，展示这个灵的长期记忆、技能和凝蜕摘要。

边界：v0.17 只读，不修改 pad/knowledge/skills/molt；不把秘密、邮箱正文或日志暴露给 Simple；不会把索引内容自动塞进模型上下文。

## v0.14 新增真实接入

### 0. avatar 绑定 / 安全退休（v0.14 新增）
- `POST /api/lingtai/avatar/bind`：把同网已有真实 LingTai agent 绑定成 Simple 本地卡片，方便后续派发、回收、生命周期管理。绑定只改 Simple 本地状态，不启动、不删除真实 agent。
- `POST /api/lingtai/avatar/retire`：退休/解绑先进入确认队列；批准后只把 Simple 本地卡片标为已退休/解绑，不删除真实 agent 目录，不提供 `nirvana`。
- 退休后动作可选：`none`（只本地退休）、`lull`（写 `.sleep`）、`suspend`（写 `.suspend`）。`lull/suspend` 只在 heartbeat 新鲜时写 signal。
- UI 中绑定了 `lingtai_address` 的卡片，“删除”按钮实际走“退休/解绑”确认闸；不会做文件系统删除。

### 1. 真实 agent 回复回收
- `POST /api/lingtai/collect`：只读扫描 `<reply_inbox>/mailbox/inbox/*/message.json`，默认 reply inbox 为 `mimo-2-5-pro`，可用 `LINGTAI_SIMPLE_REPLY_INBOX` 修改。
- 回收逻辑会按原派发 mailbox id、sender、subject 匹配 `lingtai_dispatches`，把回复写入 `lingtai_mail_results`。
- 匹配成功后会把对应 dispatch 标记为 `reply_received`，并把本地任务状态更新为“完成”，结果预览显示真实回信摘要。
- 该操作**不删除、不移动、不标记已读**真实 LingTai 邮箱；只是读入 Simple 状态，避免破坏 kernel 邮箱。

### 2. 生命周期动作确认闸
- `POST /api/lingtai/lifecycle/request`：支持 `lull` / `suspend` / `interrupt` / `clear` / `cpr`，先进入确认队列，不会立即执行。
- 批准后：
  - `lull` 写 `.sleep` signal；
  - `suspend` 写 `.suspend` signal；
  - `interrupt` 写 `.interrupt` signal；
  - `clear` 写 `.clear` signal；
  - `cpr` 在目标 heartbeat 不新鲜且有 `init.json` 时，用 `lingtai-agent run <agent_dir>` 尝试复苏。
- UI 增加“回收真实 agent 回复”和“生命周期动作”按钮；所有生命周期动作都必须确认。

边界：v0.14 仍不是完整 avatar 管理器；不会做文件删除，也不提供 nirvana。`clear` 会影响真实 agent 上下文，CPR 会尝试启动真实进程，所以必须走确认队列。

## 已真实接入能力总表

- Mac Keychain 密钥保险柜：API key 不落 JSON / 日志 / 响应。
- OpenAI-compatible 真实模型 API 调用：必须显式确认费用。
- git Time Machine / rollback：snapshot、preview、确认后真实 `git reset --hard`。
- WeChat bridge endpoint + pending outbox：不启动第二个 poller，由当前 LingTai WeChat MCP 作为唯一真实收发桥；`/api/wechat/bridge/pending` 供桥接者取待发送回复。
- Claude Code：L1 只读分析、L2 本地改码、L3 本地 commit、L4 GitHub PR、L5 GitHub merge，全部走确认/安全闸。
- 多 agent / 子灵编排：`POST /api/agent/orchestrate`，创建/选择子灵、拆任务、记录批次。
- 洞察：`POST /api/insight/generate`，本地状态分析。
- 心流：`POST /api/soul/flow`，阶段回环记录。
- 真实 LingTai 内部邮箱派发：`POST /api/lingtai/dispatch`。
- 真实 LingTai 回复回收：`POST /api/lingtai/collect`。
- 真实 LingTai 生命周期确认闸：`POST /api/lingtai/lifecycle/request` → approve 后写 signal / CPR。
- 真实 LingTai 记忆 / 技能只读索引：pad / knowledge / custom/shared skills / 最近凝蜕摘要只读可见。
- Lightweight LingTai Harness：`/api/task/route` 与 WeChat 默认入口会创建 harness run，把 intake/route/approval/dispatch/collect/return 串成可审计链。
- 统一 Task Router：`/api/task/route` 与 WeChat 默认入口可把一句话路由到普通任务、多 agent、洞察、心流、收功、真实 mailbox 派发/回收或受控 handoff。

## 从 GitHub 下载运行

完整步骤见 [`QUICKSTART.md`](QUICKSTART.md)。最小启动方式：

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuan-nutrition-mas-harness.git
cd yuan-nutrition-mas-harness
./run.sh
# 打开 http://127.0.0.1:8765/
```

You can also run `python3 server.py` directly; on macOS, double-click `Start Yuan Nutrition MAS Harness.command`.

## 自检

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
node --check static/app.js
python3 scripts/self_check.py
```

自检覆盖：Keychain 不泄露、模型调用未确认会拒绝、任务/确认队列、Time Machine snapshot/request、WeChat bridge、`/api/task/route`、`/api/wechat/bridge/pending`、Claude Code L1-L5 守门、多 agent 编排、洞察、心流、隔离 fake `.lingtai` 网络中的 router→真实 outbox 写入、fake reply inbox 中的真实回信回收、生命周期动作只进入确认队列。

## 仍未完成

- 自治式独立微信 poller（当前刻意不启动 poller；standalone HTTP connector 已提供 endpoint-driven inbound/pending/mark_sent，真实 outbound 仍需外部 WeChat provider/API/webhook 凭证）。
- 完整 LingTai avatar spawn / delete 管理；当前做到既有 agent 发现/绑定、安全 shallow spawn、退休/解绑、派发、回复回收、确认后 signal/CPR。
- skills / knowledge / molt / soul 的完整 kernel 深度接入。
- Mac app 外壳与安装体验。
- 公开发布/下载运行体验仍在继续打磨；当前已提供 `run.sh`、macOS `.command`、`QUICKSTART.md` 与 `scripts/self_check.py`。

原则：没真实接通不说接通；能真实测试的都进 self-check。


### v0.17：Secret Vault health scan + restricted fallback
`/api/health` 与 `/api/secret/scan` 会只读扫描本地状态/示例/.env/.secrets JSON 的明文 key 风险，只显示位置与字段，不回显值；发现风险时提示迁移到 Mac Keychain 或受限 env/.secrets。

---

> **禁止抄袭商用，违者等同盗法，因果自负**
> **Plagiarism and commercial use are strictly prohibited. Violators shall be deemed as thieves of sacred scriptures and shall face divine karmic retribution.**
>
> 公益开源项目，禁止商用 | Public welfare open-source project, commercial use prohibited
> License: CC BY-NC 4.0
