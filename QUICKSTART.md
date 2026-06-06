# LingTai Simple Quickstart / 轻量版灵台快速运行

This repository is designed to be runnable after a normal GitHub clone/download.
It uses Python standard library for the local server and vanilla HTML/CSS/JS for the UI.

本仓库目标：任何人从 GitHub clone/download 后，可以先在本地打开界面、跑自检；没有 API key 也能运行本地状态与安全闸，有凭证后再启用真实模型/API/微信桥接等能力。

## 1. Requirements / 环境

- Python 3.10+ recommended.
- Git is required for Time Machine / rollback features.
- macOS Keychain is used when available for API keys; on other systems, run without stored keys or use environment-based configuration later.
- Node.js is optional; only used for `node --check static/app.js` during developer validation.

No `pip install` is required for the core local UI.

## 2. Download / 下载

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuanjiang-lingtai-simple.git
cd yuanjiang-lingtai-simple
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

On macOS you may also double-click:

```text
启动圆酱灵台.command
```

## 4. Self-check / 自检

Run:

```bash
python3 scripts/self_check.py
```

Expected output:

```text
OK LingTai Simple v0.20 self-check passed
```

The self-check starts a temporary local server, builds an isolated fake `.lingtai` network, verifies task/approval flows, rollback guards, WeChat bridge endpoint behavior, Claude Code safety gates, real mailbox outbox writing in the fake network, reply collection, lifecycle approval, avatar bind/retire gates, and the v0.20 memory/skill read-only index and budget/cost guardrail panel. It also verifies `.secrets` is not readable through the memory endpoint.

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
- Time Machine snapshot/preview/request inside the local git repo.
- Read-only LingTai memory/skill index when `LINGTAI_SIMPLE_AGENT_DIR` points to a real agent directory.
- WeChat bridge HTTP endpoint for an existing LingTai WeChat MCP bridge to call.

Requires local tools or credentials:

- Model API calls require provider configuration and explicit cost confirmation.
- Key storage uses macOS Keychain when available.
- Claude Code L1/L2/L3/L4/L5 require the local `claude` CLI and explicit confirmation gates.
- GitHub PR/merge executors require `gh` login and explicit confirmation.
- Real LingTai mailbox dispatch requires `LINGTAI_SIMPLE_NETWORK_DIR` to point to a real `.lingtai` network and `confirm_dispatch=true`.

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
