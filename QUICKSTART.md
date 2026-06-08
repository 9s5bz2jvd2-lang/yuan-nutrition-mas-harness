# Yuan Nutrition MAS Harness Quickstart

This repository is designed to be runnable after a normal GitHub clone/download.
It uses Python standard library for the local server and vanilla HTML/CSS/JS for the UI. Full LingTai is not required for the lightweight harness core.

本仓库目标：任何人从 GitHub clone/download 后，可以先在本地打开界面、跑自检；没有 API key、没有 Codex/Claude CLI、没有完整 LingTai 安装也能运行本地状态、任务队列、确认闸、harness run 与预算闸。有凭证或本机工具后，再启用真实模型/API、可选 LingTai bridge、可选本地 CLI worker 等增强能力。

## 1. Requirements / 环境

- Python 3.10+ recommended.
- Git is optional for core startup and required only for Time Machine / rollback features.
- macOS Keychain is used when available for API keys; on other systems, run without stored keys or use environment-based configuration later.
- Node.js is optional; only used for `node --check static/app.js` during developer validation.
- Full LingTai is optional. Configure `LINGTAI_SIMPLE_NETWORK_DIR` only when you want controller mailbox dispatch, reply collection, or avatar/daemon bridge features. WeChat/external-channel inbound can also use the standalone HTTP connector without installing full LingTai.

No `pip install` is required for the core local UI.

## 2. Download / 下载

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuan-nutrition-mas-harness.git
cd yuan-nutrition-mas-harness
```

If you downloaded a ZIP from GitHub, unzip it and open a terminal in the extracted folder.

## 3. Start / 启动

macOS / Linux:

```bash
./run.sh
```

Or directly:

```bash
python3 server.py
```

Then open:

```text
http://127.0.0.1:8765/
```

Optional standalone status check:

```bash
curl http://127.0.0.1:8765/api/standalone/status
curl http://127.0.0.1:8765/api/connectors/status
```

`missing_core` should be empty in this repo. Missing git, LingTai, Codex, or Claude are reported as optional unavailable features, not core startup blockers.

On macOS you may also double-click:

```text
Start Yuan Nutrition MAS Harness.command
```

## 4. Self-check / 自检

Run:

```bash
python3 scripts/self_check.py
```

Expected output:

```text
OK Yuan Nutrition MAS Harness v0.24 self-check passed
```

The self-check starts a temporary local server, builds an isolated fake `.lingtai` network, verifies `/api/standalone/status` reports standalone core OK with empty `missing_core`, verifies `/api/connectors/status` and standalone WeChat HTTP inbound/pending/mark_sent behavior without leaking fake webhook secrets, and checks optional LingTai bridge semantics, task/approval flows, v0.23 harness run protocol, the read-only Harness Watchdog (`needs_attention` / stale dispatch detection / recommended actions), local-only manual harness resolution, harness recovery (`collect` is read-only; `request_retry` only creates an approval gate and does not auto-dispatch), scoped approval grants (allow-once auto-confirm + destructive-action refusal), rollback guards, WeChat bridge endpoint behavior, Claude Code safety gates, real mailbox outbox writing in the fake network, reply collection, lifecycle approval, avatar bind/retire gates, the memory/skill read-only index, budget/cost guardrail panel, and controlled worker dispatch/collection through a fake controller mailbox including HARNESS_REPLY_JSON structured result parsing, next-action/artifact/side-effect field mapping, WeChat-origin result aggregation, and the external-side-effect return gate that blocks `ready_for_bridge` outbox creation until explicit approval. It also verifies `.secrets` is not readable through the memory endpoint and that standalone status does not leak fake secret values.

Developer optional checks:

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
node --check static/app.js   # optional, if Node.js is installed
git diff --check
```

## 5. Demo state / 示例状态

To load the demo UI state:

```bash
python3 scripts/load_demo.py
python3 server.py
```

Runtime state is stored in `data/state.json` and is intentionally ignored by git.

A ZIP download without `.git` can still open the local UI and run local queue/approval/demo flows. Git-dependent Time Machine features become available when the folder is a git checkout.

## 6. Real integrations / 真实能力边界

Works locally without credentials:

- GUI big buttons and local task queue.
- Approval queue.
- Local insight / soul-flow / orchestration records.
- Harness run state and standalone status: `/api/harness/status` and `/api/standalone/status`.
- Budget/cost guardrails as local estimates.
- Time Machine snapshot/preview/request when the folder is a local git repo.
- WeChat bridge HTTP endpoints are present locally. Actual WeChat transport can use either the existing optional LingTai MCP bridge endpoints or the standalone HTTP connector endpoints. Real outbound sending still needs an external WeChat provider/API/webhook credential; the app does not start a poller or auto-send from status endpoints.
- Harness status endpoint: `/api/harness/status` shows intake/route/approval/dispatch/collect/return runs.
- Harness GUI: the existing Harness Run Protocol modal shows `side_effect_reviews` and pending/approved/denied review status, with tiny controls for read-only collect, approval-gated retry, and local-only manual resolution.
- Harness recovery endpoint: `POST /api/harness/recover` supports `action=collect` (read-only reply collection) and `action=request_retry` (create approval-gated retry; no automatic mailbox resend).

Optional local tools, credentials, or bridge configuration:

- Model API calls require provider configuration and explicit cost confirmation.
- Key storage uses macOS Keychain when available.
- Codex worker launches require the local `codex` CLI and explicit confirmation gates.
- Claude Code L1/L2/L3/L4/L5 require the local `claude` CLI and explicit confirmation gates.
- GitHub PR/merge executors require `gh` login and explicit confirmation.
- Optional LingTai bridge features require `LINGTAI_SIMPLE_NETWORK_DIR` to point to a real `.lingtai` network and, for avatar launch, `LINGTAI_SIMPLE_AGENT_CMD`. This includes controller mailbox dispatch, reply collection from a real inbox, daemon bridge, and avatar bridge.
- Optional standalone WeChat outbound configuration can use `YUAN_WECHAT_OUTBOUND_URL` or `LINGTAI_SIMPLE_WECHAT_OUTBOUND_URL`. These values may contain provider tokens, so API responses only show configured/source labels and a safe hostname, never the full URL.

## 7. Safety / 安全

- Do not commit `data/state.json`, `.secrets/`, logs, API keys, or runtime output.
- The memory/skill index is read-only and rejects `.secrets`, mailbox contents, logs, hidden files, and arbitrary paths.
- Rollback can revert tracked files in this repo, but cannot undo already-sent WeChat/email/API/GitHub side effects.
- Dangerous actions are routed through approval records; if a feature is not truly connected, the README must say so.


## Secret Vault fallback（可选）

默认优先使用 macOS Keychain 保存模型 API key。若 Keychain 在非交互环境不可用，可选择：

- 只读环境变量：`LINGTAI_SIMPLE_API_KEY_DEEPSEEK=... ./run.sh`
- 或在模型/API中心显式勾选受限 `.secrets` fallback（写入 `.secrets/providers/<provider>.key`，目录 0700、文件 0600）。
- 自检/受限环境可设 `LINGTAI_SIMPLE_DISABLE_KEYCHAIN=1` 强制不使用 Keychain。

无论哪种方式，API 响应、state、health scan 都不回显 key 明文。


## 8. License and roadmap

Yuan Nutrition MAS Harness is available under a conservative [Temporary Public Demonstration License](LICENSE). 目前为研发中临时开放展示，未经许可不得复制、商用、再分发或作为衍生系统发布。

For public-source safety notes, read [SECURITY.md](SECURITY.md). For next development steps, read [ROADMAP.md](ROADMAP.md).

Before sharing logs, screenshots, state files, or bug reports, scan and redact secrets. Before using nutrition or medical content with real users, keep human professional review in the loop.


## 启动真实 worker（v0.24）

1. 打开本地页面后点 **“真实 Worker 启动器”**。
2. 选择 `daemon / Codex / Claude / avatar`，写清楚任务或 mission。
3. Codex/Claude 需勾选费用确认；avatar 需填写合法名称并确认 mission。
4. 提交后先进入 **确认队列**；批准后才会写 controller 邮箱、启动 CLI 子进程或创建 avatar。
5. Codex/Claude 的输出会脱敏写入 `data/worker_launches/<launch_id>.md`，GUI 会显示 `report_path` 与预览。

安全边界：不要在任务描述中粘贴 token/API key；daemon 由真实 LingTai controller 执行，Web 进程本身不直接持有 daemon 工具。
