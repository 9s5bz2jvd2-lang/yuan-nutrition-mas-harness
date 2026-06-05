# LingTai Simple v0.5 Implementation Report

## 结论

v0.5 在 v0.4 的 **Mac Keychain 密钥保险柜 + OpenAI-compatible 真实模型调用 + git Time Machine / rollback** 基础上，继续接入了圆酱要求的 **真实微信指令入口**。

这次没有启动第二个微信 bot/poller，也没有保存微信凭证。安全方案是：**当前 LingTai agent 的 WeChat MCP 仍是唯一真实收发通道**；LingTai Simple 只提供 localhost 控制端点。桥接者收到圆酱微信消息后 POST 到 LingTai Simple，LingTai Simple 生成 `reply_text` 和 outbox 记录，桥接者再用现有 `wechat.reply` 原路回复。

因此 v0.5 已经能真实完成：微信消息进入 LingTai Simple → 写入任务/确认/rollback/收功流程 → 生成可原路回复的文本 → 标记 outbox 已发送。

## 已实现

- `server.py`
  - 版本升级为 v0.5，保留 localhost-only。
  - `default_state()` 增加：
    - `wechat_outbox`：待桥接者原路发回微信的回复队列。
    - `wechat_bridge`：说明桥接模式与状态。
  - 增加 `normalize_state()`：旧 v0.4 `state.json` 升级时自动补齐 v0.5 字段。
  - 新增真实微信桥接端点：
    - `POST /api/wechat/bridge/incoming`
      - 接收字段：`text`、`user_id`、`message_id`、`sender`。
      - 写入 `wechat_inbox`。
      - 路由微信命令：`状态`、`快照 <标签>`、`回滚列表`、`回滚 <snapshot_id>`、`确认 <approval_id>`、`拒绝 <approval_id>`、`收功`。
      - 非命令文字进入 LingTai Simple 任务队列；无灵时自动创建“微信主控灵”。
      - 返回 `reply_text` + `outbox` + `should_reply=true`。
    - `POST /api/wechat/bridge/mark_sent`
      - 桥接者实际 `wechat.reply` 后，将 outbox 标记为 `sent`。
  - 敏感任务确认边界修正：非 rollback 的外发/commit/merge 类动作，确认后只完成本地记录，不会假装真实执行。
  - `health_check()` 更新边界：微信入口已通过现有 LingTai WeChat MCP 桥接；仍未接入独立 poller、Claude Code 执行、commit/PR/merge。

- `static/app.js`
  - 微信卡片显示 `wechat_bridge` 状态。
  - 显示真实桥接写入的 inbox 字段（source/message_id）。
  - 显示 `wechat_outbox`：待桥接者原路回复 / 已回复。
  - 文案从“模拟微信”改为“微信入口 / 桥接测试”，说明真实运行时由当前 LingTai WeChat MCP 桥接，避免第二个 poller。

- `scripts/self_check.py`
  - 升级为 v0.5 自检。
  - 增加微信桥接验证：
    - `/api/wechat/bridge/incoming` 能接收 `状态` 并生成包含 v0.5 的 `reply_text`。
    - `/api/wechat/bridge/mark_sent` 能把 outbox 标记为 `sent`。
    - 普通微信任务能进入任务队列并生成 outbox。
  - 继续验证 Keychain 安全路径、假 key 不落盘、模型调用未确认费用时拒绝、Time Machine snapshot/request。

- `README.md`
  - 重写为 v0.5：已接入 / 未接入分清。
  - 新增“微信桥接怎么用”示例，包含 `curl /api/wechat/bridge/incoming` 和 `mark_sent`。
  - 明确：本服务不直接轮询/发送微信，不持有微信凭证；真实发送仍由当前 LingTai WeChat MCP 完成。

## 已验证

运行：

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

期望结果：

```text
OK LingTai Simple v0.5 self-check passed
```

自检不调用真实外部模型 API；只验证未确认费用时会被拒绝。

## 真实能力边界

- 微信桥接是真实控制链路，但不是独立微信客户端：必须由当前 LingTai agent / WeChat MCP 作为唯一桥接者调用本地端点并原路回复。
- v0.5 不启动第二个 poller，避免抢消息、重复 ACK 或凭证冲突。
- rollback 只能回滚本仓库 tracked/unignored 文件状态，不能撤回已发微信、邮件、Telegram、模型 API 调用、GitHub PR/merge、外部服务等副作用。
- 非 rollback 的敏感动作（外发、commit、PR、merge）当前确认后只记录为已确认，不会真实执行。
- API key 只进 Keychain；Keychain 不可用时失败，不退化为明文 JSON。

## 未实现 / 不算完成

- 独立微信 bot/poller（当前刻意不做；采用现有 LingTai WeChat MCP 桥接）。
- 常驻 bridge runner/skill（目前是端点已就绪，桥接可由当前 agent 或后续 runner 调用）。
- 真实 Claude Code worker。
- 真实 commit / push / PR / merge。
- 真正的 Mac app 外壳。
- 与 LingTai runtime/mailbox/skills/memory 的完整接入。

## 下一步建议

1. **把微信桥接常驻化**：写一个受控 bridge runner 或 skill，让当前 LingTai agent 自动把圆酱微信消息转进 LingTai Simple，再把 `reply_text` 原路回复。
2. **接真实 Claude Code worker**：受控 worktree + 权限等级 + 测试/扫描 + commit/PR/merge 确认闸。
3. **接 LingTai runtime/mailbox/skills/memory**：让“灵”的状态不只是本地卡片，而能真正派给灵台分身。
4. **Mac app 包装**：降低启动门槛。
