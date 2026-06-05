# Claude Code 独立审查 / Independent Review — LingTai Simple v0.2

**审查对象**：`projects/lingtai_simple_20260605/simple_prototype`
**审查日期**：2026-06-05
**审查模式**：只读（READ-ONLY）。未修改任何文件；未 commit/push/建库；未调用任何真实外部 API；未回显任何疑似密钥。
**审查者**：Claude Code (independent reviewer)

---

## Verdict（结论）

**✅ 可以推送（SAFE TO PUSH）。** 未发现阻断性问题（no blockers）。

该原型符合其声明的硬红线：localhost-only、所有高危动作仅 mock/preview、敏感动作强制进确认队列、API key 不落盘明文且界面/日志/产物均脱敏。代码语法正确，自检脚本通过，安全声明经独立实测验证。

下方「Required Fixes」为空；少量「Nice-to-Have」为推送后改进项，不阻断推送。

---

## Checks Run（已执行的检查）

| # | 检查 | 结果 |
|---|---|---|
| 1 | `py_compile` — `server.py` / `scripts/self_check.py` / `scripts/load_demo.py` | ✅ PY_COMPILE_OK（全部通过） |
| 2 | `scripts/self_check.py`（端口 8799，临时启动 → 自检 → 自动清理） | ✅ `OK LingTai Simple v0.2 self-check passed`，并在结束后删除运行态 `state.json` |
| 3 | 阅读 `README.md` / `IMPLEMENTATION_REPORT.md` | ✅ 启动说明清晰、边界声明明确 |
| 4 | 阅读 `server.py`（路由、状态、脱敏、确认队列、localhost 守卫） | ✅ 见 Findings |
| 5 | 阅读 `static/index.html` / `styles.css`(略读) / `app.js`（前端副作用） | ✅ 仅同源相对 `fetch`，无外部端点 |
| 6 | 外部副作用扫描：`urllib`/`requests`/`socket`/`smtplib`/`subprocess`/`Popen`/`fetch`/`webhook` 等 | ✅ 无真实外发；`server.py` 仅用 `urllib.parse`（不联网）；`self_check.py` 的 `urllib`/`subprocess` 仅打到 `127.0.0.1`；`app.js` 的 `fetch` 全为相对路径 |
| 7 | 高置信度密钥扫描：`sk-`/`ghp_`/`xox*`/`AKIA`/`BEGIN PRIVATE KEY`/`Bearer`/`password`/`secret`/Telegram bot token 模式 | ✅ 无命中（仅自检脚本中的**示例假 key** `sk-v0-2-secret-ABCDEFGH`，非真实凭证） |
| 8 | 实测：保存带密钥的供应商 → 检查返回与落盘 | ✅ 返回仅 `configured=True` + `key_last4=ABCD`，**无 `api_key` 字段**；`state.json` 中 grep 真实密钥串命中 **0**（NO_PLAINTEXT_KEY_OK） |
| 9 | 实测：敏感任务（含 `sk-...` 串）派发 | ✅ 任务进入「等确认」队列；任务描述中的密钥被脱敏（REDACTED） |
| 10 | `.gitignore` 与生成产物核对（`git check-ignore`） | ✅ `data/state.json`、`data/shougong/`、`__pycache__/`、`*.pyc`、`*.log` 均被正确忽略；当前仓库中该目录暂无任何已跟踪文件 |

---

## Findings（发现）

### 安全边界（均已满足）

- **Localhost-only（双重保障）**：默认 `HOST=127.0.0.1`（`server.py:35`）；且每个 GET/POST 入口先经 `_guard_local()`（`server.py:642–648, 652, 683`）——非 `127.0.0.1/::1/localhost` 的 `client_address` 直接返回 403。即使用户改 `LINGTAI_SIMPLE_HOST` 暴露端口，请求层仍会拒绝外部来源。
- **全部高危动作 mock-only**：`wechat/email/telegram_send`、`code_commit/pr/merge`、`rollback_apply`、`delete_agent`、`high_cost_api` 均仅生成 preview，确认后走 `_apply_approved_action()`（`server.py:367–380`）——只改本地 JSON 状态，**绝无真实副作用**（注释明确：「确认后的 mock 执行：绝不产生真实副作用」）。
- **敏感动作强制确认队列**：`assign_task` 对 `risk=="sensitive"` 入队（`server.py:267–277`）；`request_cc_task` 对 level≥2 入队，merge（level 5）`needs_approval=True` 必经确认（`server.py:64–70, 537–555`）；微信入口含敏感关键词（发/提交/commit/merge/PR/回退/rollback/删除）自动入队（`server.py:423, 447–450`）；删除灵也走确认队列（`server.py:296–304`）。
- **密钥安全（实测通过）**：`save_provider` 仅用原始 key 取后四位，**从不写入 `api_key`**（`server.py:383–408`）；`_public_state` 防御性 `pop("api_key")`（`server.py:728–731`）；全局 `redact()` 对 `sk-…`、32+ 长串、`Bearer …` 脱敏，应用于日志、任务描述、收功单、确认项与 HTTP 访问日志（`server.py:86–100, 605–608`）；前端 key 输入框为 `type="password"`、提示「不会被保存为明文」（`app.js:313–314`）。
- **≤5 个灵硬上限**：`create_agent`（`server.py:204–205`）。
- **原子写状态**：`save_state` 用 tmp + `os.replace`（`server.py:174–180`）并在 `_LOCK` 下串行化，避免并发写损坏。

### README / 启动说明

- 启动说明清晰：`cd simple_prototype && python3 server.py` → `http://127.0.0.1:8765/`；自定义端口示例、停止方式（Ctrl+C）、零第三方依赖均已写明。
- 提供 Mac 双击启动 `启动圆酱灵台.command`（`set -euo pipefail`，自动 `open` 本地 URL，仅打到 127.0.0.1）——合理且安全。
- README、IMPLEMENTATION_REPORT 对「哪些是 mock / 边界 / 凭证安全」的描述与实际代码一致，无夸大。

### 观察到的次要点（非阻断）

1. **过宽的脱敏正则**：`\b[A-Za-z0-9_\-]{32,}\b`（`server.py:89`）会把任意 32+ 位字母数字串（如某些长 ID/hash/base_url path 段）也替换为 `****REDACTED****`。对安全是「偏保守」（不会泄露），但可能误伤展示文本。可接受，属保守取向。
2. **`request_cc_task` 内死代码**：`server.py:548–549` 的 `"file_delete" if False else "code_commit"` 与第 550 行 `action if level >= 3 else "code_commit"`（此处 `action` 已被覆盖）逻辑冗余、可读性差。功能正确（level 2→code_commit 入队），仅清理项。
3. **`load_demo` 覆盖确认提示在前端**（`app.js:425`），后端 `/api/demo/load` 直接覆盖 `state.json`。原型可接受；前端已 `confirm`。
4. **`state.json` 损坏即重置**（`server.py:167–171`）——原型容错，IMPLEMENTATION_REPORT 已列为已知限制。
5. **`scripts/self_check.py` 含示例假 key** `sk-v0-2-secret-ABCDEFGH`（`scripts/self_check.py:26`）——是用于验证「不落盘明文」的测试夹具，**非真实凭证**，无需处理，但留意它会被 redact 正则覆盖到，属预期。

---

## Required Fixes Before Push（推送前必须修）

**无（None）。** 未发现任何阻断性问题。可按 README 直接推送到 Runyuan 的 GitHub。

> 提醒（非代码问题）：推送时确认仅提交 `simple_prototype/` 源码与 `state.example.json`；运行态 `data/state.json` 与 `data/shougong/*.md`、`__pycache__/`、`*.pyc` 已由 `.gitignore` 正确排除——保持现状即可，无需手动清理。

---

## Nice-to-Have After Push（推送后可做）

1. **清理 `request_cc_task` 死代码**（`server.py:548–550`）：删除 `if False` 分支与被覆盖的 `action` 赋值，让 level→action 映射一目了然。
2. **收紧 32+ 位脱敏正则**：可改为带常见前缀/上下文的匹配，减少对正常长字符串的误伤；或对该模式仅在 key 相关字段启用。
3. **Secret Vault 升级 Mac Keychain**（README 已列入下一步）：彻底避免明文 key 进入进程内存以外的任何路径。
4. **为 `self_check.py` 增加 localhost 守卫负向测试**：模拟非 127.0.0.1 来源被 403 拒绝（当前守卫仅靠代码审查与正向实测确认）。
5. **轻量端口占用提示**：若 8765 被占用，`server.py` 当前会抛 `OSError`；可捕获后给出更友好的中文提示。

---

## 附：独立实测命令摘要（仅打本机，未触外网）

```
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py   # PY_COMPILE_OK
LINGTAI_SIMPLE_TEST_PORT=8799 python3 scripts/self_check.py                  # self-check passed
# 实测保存带密钥供应商 → 返回仅 last4，无 api_key 字段；state.json grep 真实密钥串 = 0
# 实测敏感任务 → 状态「等确认」（进确认队列）；描述中 sk-… 被脱敏
```

— 审查结束。结论：**SAFE TO PUSH**，无阻断项。
