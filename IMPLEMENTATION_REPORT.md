# LingTai Simple v0.4 Implementation Report

## 结论

v0.4 在 v0.3 的 **Mac Keychain 密钥保险柜 + OpenAI-compatible 真实模型调用** 基础上，又接入了一项圆酱明确要求的真实能力：**git Time Machine / rollback**。

现在“时间机器”不再是 mock：它能创建真实 git 快照 ref、列出快照与 diff/stat，rollback request 进入确认队列，批准后执行真实 `git reset --hard`。执行 reset 前会自动创建 safety ref。

仍然没有接通的能力继续标为未接入：微信 bot、Claude Code worker、真实 commit/push/PR/merge、完整 LingTai runtime/mailbox/skills/memory。

## 已实现

- `server.py`
  - 默认绑定 `127.0.0.1`。
  - provider 配置保存：base_url/model 写入本地状态；API key 写入 Mac Keychain。
  - Keychain 通过 macOS `Security.framework` + Python `ctypes`，避免 `security -w <key>` 把 key 暴露在子进程 argv。
  - `/api/model/test` 发起真实 OpenAI-compatible `/chat/completions` 请求；需要 `confirm_cost=true`。
  - 新增 git Time Machine：
    - `POST /api/rollback/snapshot` 创建真实 snapshot ref：`refs/lingtai-simple/snapshots/...`。
    - `GET /api/rollback/preview` 列 snapshot/safety refs、当前 HEAD、工作区状态、diff/stat。
    - `POST /api/rollback/request` 把 rollback 加入确认队列。
    - 批准 `/api/approval/approve` 后，对 `rollback_apply` 执行真实 `git reset --hard <snapshot_commit>`。
    - reset 前自动创建 `refs/lingtai-simple/safety/...`，保留回退前状态。
  - 错误与日志继续走脱敏。

- `static/index.html` / `static/app.js` / `static/styles.css`
  - “时间机器 / Rollback”按钮重新启用，标为真实能力。
  - UI 支持创建快照、查看当前 HEAD/dirty 状态、查看快照 diff、把回退请求加入确认队列。
  - 文案更新：rollback 会真实 reset；外部副作用无法撤回。
  - 微信 bot / Claude Code 仍灰显或标注下一阶段，不当成完成。

- `scripts/self_check.py`
  - 升级为 v0.4 自检。
  - 仍不调用真实外部模型 API。
  - 验证 Keychain 安全路径、假 key 不落盘、未确认费用时模型调用被拒绝。
  - 新增验证：创建真实 git snapshot ref，并把 rollback request 加入确认队列；自检结束清理创建的 ref。

- `README.md`
  - 重写为 v0.4：已接入 / 未接入分清。
  - 新增 Time Machine 使用方式、API 表、边界说明。

## 已验证

运行：

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

结果：

```text
OK LingTai Simple v0.4 self-check passed
```

说明：当前 agent 非交互 session 下 Keychain 写入可能被系统拒绝；这是安全失败路径。自检确认没有退化为明文存储。

另外做了隔离临时目录 destructive smoke test：

1. 复制当前仓库到 `/tmp/lingtai-simple-rollback-test.*`。
2. 启动临时 server。
3. 创建 snapshot。
4. 往 README 加测试 marker。
5. 请求 rollback，批准确认队列。
6. 验证真实 `git reset --hard` 后 marker 被删除。

结果：

```text
OK destructive rollback apply smoke passed
```

该测试只在临时复制仓库中执行，不会破坏当前工作仓库。

## 真实能力边界

- rollback 只能回滚本仓库 tracked/unignored 文件状态。
- rollback 不能撤回：已发微信、邮件、Telegram、模型 API 调用、GitHub PR/merge、外部数据库/服务等副作用。
- 被 `.gitignore` 忽略的运行时文件（例如 `data/state.json`、`data/shougong/`）不作为代码快照核心目标。
- 批准 rollback 是真实本地破坏性动作，所以必须走确认队列；执行前会建 safety ref。

## 未实现 / 不算完成

- 真实微信 bot 指令入口。
- 真实 Claude Code worker。
- 真实 commit / push / PR / merge。
- 真正的 Mac app 外壳。
- 与 LingTai runtime/mailbox/skills/memory 的完整接入。

## 下一步建议

圆酱最新明确要求：每一项都要认真做，不能 mock 冒充。所以下一阶段优先级：

1. **接真实 WeChat bot / mailbox 路由**：微信发指令 → 本地服务/控制桥收到 → 入任务队列 → 执行 → 结果回微信。
2. **建立微信二次确认协议**：高危动作通过微信确认；确认记录进入本地审计日志。
3. **接真实 Claude Code worker**：受控 worktree + 权限等级 + 测试/扫描 + commit/PR/merge 确认闸。
4. **再做 Mac app 包装**。
