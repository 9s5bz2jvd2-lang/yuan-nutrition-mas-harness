# 圆酱专属轻量版灵台 / LingTai Simple v0.9

这是“傻瓜版灵台”的本地可运行原型。v0.9 在 v0.8 的 **Mac Keychain、真实模型 API、git Time Machine / rollback、微信桥接入口、Claude Code L1 只读分析、L2 本地改码、L3 本地 commit** 基础上，新增 **真实 GitHub PR / merge 执行闸**。

核心原则：每一项都诚实标注。已接入的能力就真实可用；高危动作必须进入确认队列；未确认前不会执行外部副作用。

## v0.9 已真实接入

1. **Mac Keychain 密钥保险箱**
   - API key 只写入 macOS Keychain。
   - 不把明文 key 写入 `state.json`、日志或 API 响应。

2. **真实模型 API 调用**
   - 支持 OpenAI-compatible `/chat/completions`。
   - 供应商入口：OpenAI-compatible、DeepSeek、GLM、MiMo/MiniMax 自定义端点、自定义 base_url + model。
   - 必须在 UI/API 显式确认可能产生费用。

3. **真实 git Time Machine / rollback**
   - 可创建 git 安全快照 ref。
   - 可预览 diff/stat。
   - rollback 必须先进入确认队列；批准后执行真实 `git reset --hard <snapshot>`。
   - reset 前自动创建 safety ref。

4. **真实微信桥接入口**
   - 不启动第二个微信 poller，不保存微信凭证。
   - 当前 LingTai WeChat MCP 作为唯一桥接者，把真实微信消息 POST 到 `/api/wechat/bridge/incoming`，再按返回的 `reply_text` 原路回复。

5. **真实 Claude Code L1 只读分析**
   - `POST /api/cc/request`，`level=1` 且 `confirm_cost=true` 时真实调用本机 `claude --print`。
   - 只允许 `Read,Grep,Glob`；禁用 `Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch`。
   - 输出写入 `data/cc_runs/<run_id>.md`。

6. **真实 Claude Code L2 本地改码（不提交）**
   - `level=2` 且 `confirm_cost=true` 时真实调用 Claude Code。
   - 先要求主仓库干净并创建 safety ref。
   - 在隔离 git worktree 中允许 `Read,Grep,Glob,Edit,Write`，禁用 `Bash` 与 Web 工具。
   - Claude 修改后生成 patch；通过 `py_compile` 与高置信秘密扫描后，才把 patch 应用回本仓库。
   - 不 commit；改动留在本地供人工审查。

7. **真实 Claude Code L3 本地 commit**
   - `level=3` 时不调用外部模型；它只把当前未提交改动整理成确认项。
   - 入队前检查：有未提交改动、文件数 ≤120、`py_compile` 通过、高置信秘密扫描通过。
   - 批准后再次复查工作区文件清单必须与预览时完全一致，然后只 `git add -- <approved_paths>` 并创建真实本地 commit。
   - commit 前创建 `refs/lingtai-simple/safety/pre-commit-*`。
   - 不 push、不 PR、不 merge。

8. **真实 Claude Code L4 GitHub PR**
   - `level=4` 时创建一个确认项；批准前不会 push。
   - 入队前检查 `gh` 登录账号必须是 `9s5bz2jvd2-lang`，工作区必须干净，HEAD 相对 `origin/<base>` 必须有新 commit。
   - 批准后用 `gh auth token` 通过临时 `GIT_ASKPASS` 安全 push 分支，并执行真实 `gh pr create`。
   - 只创建 PR，不 merge。

9. **真实 Claude Code L5 GitHub merge**
   - `level=5` 时必须在描述里写 PR 编号或 URL，例如 `#12` 或 `/pull/12`。
   - 入队前读取 PR 状态，要求 PR 为 OPEN 且非 draft。
   - 批准后执行真实 `gh pr merge`，默认 `--merge --delete-branch`。
   - 这是远端外部副作用；本地 rollback 不能撤回已 merge 的 GitHub 状态。

## 尚未真实接入

- **独立常驻微信 runner**：当前是桥接 endpoint，需要现有 LingTai WeChat MCP 转发。
- **完整 LingTai runtime/mailbox/skills/memory 接入**：v0.9 仍是轻量控制层原型。

## 运行

```bash
python3 server.py
# 打开 http://127.0.0.1:8765/
```

或双击：`启动圆酱灵台.command`

## Claude Code / GitHub 用法

### L3 本地 commit

```bash
curl -s -X POST http://127.0.0.1:8765/api/cc/request   -H 'Content-Type: application/json'   -d '{"level":3,"description":"feat: describe the current local changes"}'
```

### L4 创建 GitHub PR

```bash
curl -s -X POST http://127.0.0.1:8765/api/cc/request   -H 'Content-Type: application/json'   -d '{"level":4,"description":"feat: add GitHub PR executor","branch_name":"feat/lingtai-simple-v09-pr-executor","base_branch":"main"}'
```

返回确认项后，必须在 UI 或 `/api/approval/approve` 中批准，才会真实 push + create PR。

### L5 merge GitHub PR

```bash
curl -s -X POST http://127.0.0.1:8765/api/cc/request   -H 'Content-Type: application/json'   -d '{"level":5,"description":"#12","merge_method":"merge"}'
```

返回确认项后，必须再次批准，才会真实 merge。

## API 摘要

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/state` | 当前公开状态 |
| GET | `/api/catalog` | 模型供应商与 Claude Code 权限等级 |
| GET | `/api/rollback/preview` | 快照列表与 diff 预览 |
| POST | `/api/provider/save` | 保存供应商配置；key 进 Keychain |
| POST | `/api/model/test` | 真实模型 API 测试，需费用确认 |
| POST | `/api/wechat/bridge/incoming` | 真实微信桥接入口 |
| POST | `/api/rollback/snapshot` | 创建真实 git 快照 |
| POST | `/api/rollback/request` | 请求 rollback，进入确认队列 |
| POST | `/api/approval/approve` | 批准确认项；rollback、L3 commit、L4 PR、L5 merge 会真实执行 |
| POST | `/api/cc/request` | Claude Code：L1/L2/L3/L4/L5 分级执行或入确认队列 |
| POST | `/api/shougong` | 生成收功单 |

## 自检

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

自检默认不烧外部 Claude Code 或模型费用，不会真实 push/merge；真实 PR/merge 通过隔离临时远端 destructive smoke 验证。

## 安全边界

- rollback 只能回滚本仓库 tracked/unignored 文件，不能撤回已发微信/邮件/API 请求/PR/merge 等外部副作用。
- L2 本地改码会真实修改本仓库文件；运行前要求仓库干净，运行后必须人工看 diff。
- L3 本地 commit 会真实创建本地 git commit；它只暂存预览时已审阅且确认时仍一致的文件清单。
- L4 会真实 push 分支并创建 GitHub PR；L5 会真实 merge PR。二者都必须显式确认。
- 任何疑似 API key / token 的任务描述会被拒绝发送给 Claude Code 或写入 commit/PR 文案。
