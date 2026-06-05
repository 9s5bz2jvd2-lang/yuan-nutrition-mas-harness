# 圆酱专属轻量版灵台 / LingTai Simple v0.6

> **原则：只把已经真实接入、可验证的能力写成“已完成”。未接入能力必须写进“下一步”，不再用 mock 冒充能用。**

这是“傻瓜版灵台”的本地可运行原型。v0.6 在 v0.5 的 **Mac Keychain + 真实模型 API + git Time Machine / rollback + 微信桥接入口** 基础上，继续接入了 **真实 Claude Code L1 只读分析 worker**。

关键设计：仍然 **不启动第二个微信 poller**，避免和当前 LingTai 的 WeChat MCP 抢消息；微信真实收发由当前 LingTai/WeChat MCP 作为唯一桥。Claude Code 目前只开放 L1 只读分析：需要显式确认可能产生费用，只允许 Read/Grep/Glob，不允许改文件、commit、PR、merge。

## v0.6 已真实接入

1. **真实微信指令入口（桥接版）**
   - `POST /api/wechat/bridge/incoming`：接收当前 LingTai WeChat MCP 桥接过来的真实微信消息。
   - 消息会写入 `wechat_inbox`，可路由到状态、收功、快照、回滚、确认/拒绝、本地任务队列。
   - 返回 `reply_text`，桥接者可用现有 `wechat.reply` 原路回微信。
   - `POST /api/wechat/bridge/mark_sent`：桥接者实际发回微信后，把 outbox 标记为已发送。
   - 边界：本服务不保存微信凭证、不轮询微信、不直接发微信；真实发送仍由当前 LingTai WeChat MCP 完成。

2. **Mac Keychain 密钥保险柜**
   - API key 只进 macOS Keychain。
   - 不写入 `state.json` / README / 日志 / API 响应。
   - 非 macOS 或 Keychain 不可用时，明确报错，绝不退化成明文落盘。

3. **真实 OpenAI-compatible 模型 API 调用**
   - 支持 GPT/OpenAI-compatible、DeepSeek、GLM/智谱、自定义 base_url；MiMo/MiniMax 留给用户填写兼容端点。
   - 必须在 UI 显式确认“可能产生费用”后才发请求。
   - 单次测试有 timeout 和 max_tokens 上限。

4. **真实 git Time Machine / rollback**
   - `POST /api/rollback/snapshot` 创建真实 git 快照 ref。
   - `GET /api/rollback/preview` 列快照、dirty 状态和 diff/stat 预览。
   - `POST /api/rollback/request` 进入确认队列。
   - `/api/approval/approve` 后对 `rollback_apply` 执行真实 `git reset --hard`。
   - reset 前自动创建 safety ref。
   - 边界：只能回滚本仓库 tracked/unignored 文件，不能撤回已发微信/邮件/API/PR/merge 等外部副作用。

5. **真实 Claude Code L1 只读分析 worker**
   - `POST /api/cc/request`，`level=1` 且 `confirm_cost=true` 时，真实调用本机 `claude --print`。
   - 权限约束：`--permission-mode plan`，只开放 `Read,Grep,Glob`，显式禁用 `Bash,Edit,Write,...`。
   - 输出写入 `data/cc_runs/<run_id>.md`，并在 UI 里显示预览。
   - 任务描述若疑似包含 API key / token，会被拒绝，避免把凭证送给外部模型。
   - L2+ 本地改码、commit、PR、merge **尚未真实接入**；只进入确认队列并诚实标注。

## 尚未真实接入（不算完成功能）

- **Claude Code L2+ 改码 / commit / PR / merge**：还未接入受控 worktree、测试、秘密扫描和 GitHub 确认闸。
- **独立微信 bot/poller**：刻意不做；当前采用“现有 LingTai WeChat MCP 作为唯一桥接者”的安全方案。
- **Telegram / 邮件外发桥接**：未接入。
- **完整 LingTai runtime/mailbox/skills/memory 接入**：v0.6 仍是轻量控制与状态层。
- **Mac 原生 App 包装**：目前仍是本地 Python + 浏览器 GUI。

## 运行方式

```bash
cd /path/to/yuanjiang-lingtai-simple
python3 server.py
# 浏览器打开 http://127.0.0.1:8765/
```

或在 Mac 上双击：

```text
启动圆酱灵台.command
```

## 微信桥接怎么用

本仓库提供本地控制端点；实际微信收发由当前 LingTai agent 的 WeChat MCP 负责。桥接者收到圆酱微信消息后，向本服务写入：

```bash
curl -s http://127.0.0.1:8765/api/wechat/bridge/incoming \
  -H 'Content-Type: application/json' \
  -d '{"text":"状态","user_id":"<wechat user id>","message_id":"<wechat message id>","sender":"圆酱"}'
```

返回示例：

```json
{
  "ok": true,
  "result": {
    "should_reply": true,
    "reply_text": "圆酱，LingTai Simple v0.6 当前状态：...",
    "outbox": {"id": "wxout_xxx", "status": "ready_for_bridge"}
  }
}
```

桥接者用现有 `wechat.reply` 把 `reply_text` 原路发回圆酱，再调用：

```bash
curl -s http://127.0.0.1:8765/api/wechat/bridge/mark_sent \
  -H 'Content-Type: application/json' \
  -d '{"outbox_id":"wxout_xxx","sent_message_id":"<real sent msg id>"}'
```

微信文本命令包括：

```text
状态
收功
快照 <标签>
回滚列表
回滚 <snapshot_id>
确认 <approval_id>
拒绝 <approval_id>
```

## Claude Code 只读分析怎么用

UI 中点击“Claude Code（L1 真实只读）”，选择“只读分析”，填写任务，勾选费用确认。也可以直接调用：

```bash
curl -s http://127.0.0.1:8765/api/cc/request \
  -H 'Content-Type: application/json' \
  -d '{"level":1,"description":"只读分析这个仓库的 README 结构，不要改文件","confirm_cost":true}'
```

若不勾选 `confirm_cost`，请求会被拒绝，不会调用 Claude Code。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | GUI 页面 |
| GET | `/api/state` | 当前公开状态（不含任何 key） |
| GET | `/api/catalog` | 模型供应商与 Claude Code 权限等级 |
| GET | `/api/health` | 本地健康检查 |
| POST | `/api/provider/save` | 保存 provider 配置；有 key 时写入 Keychain |
| POST | `/api/model/test` | 显式确认后发起真实模型测试 |
| POST | `/api/wechat/bridge/incoming` | 真实微信桥接入口 |
| POST | `/api/wechat/bridge/mark_sent` | 标记微信 outbox 已原路回复 |
| POST | `/api/rollback/snapshot` | 创建真实 git 快照 |
| GET | `/api/rollback/preview` | 预览快照与 diff |
| POST | `/api/rollback/request` | 请求 rollback，进入确认队列 |
| POST | `/api/approval/approve` | 批准敏感动作；rollback 会真实执行 |
| POST | `/api/cc/request` | Claude Code；L1 只读分析可真实执行，L2+ 仅确认队列 |
| POST | `/api/shougong` | 生成收功单 |

## 验证

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

期望输出：

```text
OK LingTai Simple v0.6 self-check passed
```

自检默认不会真实调用外部模型，也不会真实调用 Claude Code；它验证这些真实外部调用在未确认费用时会被拒绝。

## 下一步

1. **受控 Claude Code L2+ worker**：隔离 worktree、本地改码、测试、秘密扫描、commit/PR/merge 确认闸。
2. **把微信桥接常驻化**：写一个更稳定的 bridge runner/skill，让当前 LingTai agent 自动把圆酱微信消息转进 LingTai Simple，再把 `reply_text` 原路回复。
3. **更完整的 LingTai runtime 接入**：mailbox、skills、knowledge、molt/context pressure 与子 agent 执行链。
4. **Mac 小应用包装**：让圆酱不需要开终端也能启动。

## 安全红线

- 不把明文 API key 写入仓库、JSON、日志或回复。
- 不启动第二个微信 poller。
- 不把“未接入”包装成“已完成”。
- rollback 只回滚本仓库文件，不承诺撤销外部副作用。
- Claude Code 当前只读分析不得改文件；改码/commit/PR/merge 必须等后续真实执行器与确认闸完成。
