# 圆酱专属轻量版灵台 / LingTai Simple v0.5

> **原则：只把已经真实接入、可验证的能力写成“已完成”。未接入能力必须灰显或写进“下一步”，不再用 mock 冒充能用。**

这是“傻瓜版灵台”的本地可运行原型。v0.5 在 v0.4 的 **Mac Keychain + 真实模型 API + git Time Machine / rollback** 基础上，继续接入了圆酱明确要求的 **真实微信指令入口（桥接版）**。

关键设计：**不启动第二个微信 poller**，避免和当前 LingTai 的 WeChat MCP 抢消息；由当前灵台/WeChat MCP 作为唯一真实收发桥，把圆酱微信消息写入本服务，再把本服务生成的回复原路发回微信。

## v0.5 已真实接入

1. **真实微信桥接入口（新增）**
   - `POST /api/wechat/bridge/incoming`：接收当前 LingTai WeChat MCP 桥接过来的真实微信消息。
   - 消息会写入 `wechat_inbox`、进入任务/确认/rollback/收功等本地流程。
   - 返回 `reply_text`，桥接者可用现有 `wechat.reply` 原路回微信。
   - 支持微信命令：
     - `状态` / `status`：返回灵数量、待确认、最近任务。
     - `快照 <标签>`：创建真实 git Time Machine 快照。
     - `回滚列表`：列出可回滚快照。
     - `回滚 <snapshot_id>`：把 rollback 放入确认队列。
     - `确认 <approval_id>` / `拒绝 <approval_id>`：处理确认队列。
     - `收功`：生成本地收功单。
     - 其他文字：作为微信任务写入 LingTai Simple 任务队列。
   - `POST /api/wechat/bridge/mark_sent`：桥接者实际发回微信后，把 outbox 标记为已发送。
   - 边界：本服务本身不保存微信凭证、不直接轮询微信、不单独发送微信；真实发送仍由当前 LingTai WeChat MCP 完成。

2. **Mac Keychain 密钥保险柜**
   - API Key 写入 macOS 系统 Keychain。
   - `state.json`、日志、接口响应不保存明文 key。
   - 通过 macOS `Security.framework` + Python `ctypes` 调用 Keychain，不把 key 放进 shell 命令参数。
   - Keychain 不可用或系统拒绝时直接报错，不退化成明文存储。

3. **真实模型 API 调用**
   - 支持 OpenAI-compatible `/chat/completions`。
   - UI 必须显式点击“运行真实模型测试”，并勾选“可能产生费用”，才会发起网络请求。
   - 单次测试有 timeout 与 token 上限，避免误烧钱。
   - 支持配置：GPT/OpenAI-compatible、DeepSeek、GLM/智谱、自定义 `base_url + model`；小米 MiMo、MiniMax 先保留为可填写自定义兼容端点，不硬编未核验 URL。

4. **git Time Machine / rollback（真实本地副作用）**
   - `POST /api/rollback/snapshot`：把当前工作树创建为 git 安全快照 ref（不移动当前分支）。
   - `GET /api/rollback/preview`：列出 snapshot/safety refs，展示当前 HEAD、工作区状态、到快照的 diff/stat 预览。
   - `POST /api/rollback/request`：把目标快照加入确认队列。
   - 批准确认队列后：执行真实 `git reset --hard <snapshot_commit>`。
   - 执行 reset 前会自动创建 safety ref，方便找回 reset 前状态。
   - 边界：只能回滚本仓库文件；不能撤回已发微信/邮件/API 请求/PR/merge 等外部副作用；被 `.gitignore` 忽略的运行时文件（如 `data/state.json`）不作为代码快照核心目标。

5. **本地 GUI / 状态管理**
   - 大按钮界面、最多 5 个“灵”的本地状态卡。
   - 本地任务停车场、确认队列、一键收功 Markdown、健康检查。
   - 微信卡片会显示桥接状态、inbox 和 outbox；这是真实控制端点的状态，不是独立微信客户端。

## v0.5 尚未真实接入（不算完成功能）

- **独立微信 bot/poller**：刻意不做；当前采用“现有 LingTai WeChat MCP 作为唯一桥接者”的安全方案。
- **Claude Code 真实苦力**：受控 worktree、权限分级、本地改码、commit、PR、merge 还未接入。
- **真实 commit/push/PR/merge**：目前不从此应用执行。
- **Telegram / 邮件外发桥接**：未接入。
- **Mac 小应用外壳**：当前仍是 localhost Web + 双击启动脚本。
- **完整 LingTai runtime/mailbox/skills/memory 接入**：v0.5 只接了轻量控制与状态层。

## 运行方式

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuanjiang-lingtai-simple.git
cd yuanjiang-lingtai-simple
python3 server.py
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

也可以双击：

```text
启动圆酱灵台.command
```

停止：`Ctrl+C`。

## 微信桥接怎么用

本仓库提供的是本地控制端点；实际微信收发由当前 LingTai agent 的 WeChat MCP 负责。桥接者收到圆酱微信消息后，向本服务写入：

```bash
curl -s http://127.0.0.1:8765/api/wechat/bridge/incoming \
  -H 'Content-Type: application/json' \
  -d '{"text":"状态","user_id":"<wechat user id>","message_id":"<wechat message id>","sender":"圆酱"}'
```

返回里会有：

```json
{
  "ok": true,
  "result": {
    "reply_text": "...",
    "outbox": {"id": "wxout_xxx", "status": "ready_for_bridge"},
    "should_reply": true
  }
}
```

桥接者用现有 `wechat.reply` 把 `reply_text` 原路发回圆酱，再调用：

```bash
curl -s http://127.0.0.1:8765/api/wechat/bridge/mark_sent \
  -H 'Content-Type: application/json' \
  -d '{"outbox_id":"wxout_xxx","sent_message_id":"<sent id>"}'
```

这样 LingTai Simple 能真实记录“微信进来—处理—原路回复”的闭环，同时避免第二个 bot 进程抢消息。

## 使用真实模型 API

1. 打开“模型 / API 中心”。
2. 选择供应商，填写 `base_url`、`model`、API key。
3. 保存后，key 会进入 Mac Keychain；界面只显示“已配置”和后四位。
4. 勾选“我已知道这是真实调用、可能产生费用”。
5. 点击“运行真实模型测试”。

> 如果 Keychain 被系统拒绝（例如无交互 session、钥匙串锁定），保存 key 会失败；这是安全失败，不会把 key 写到 JSON 文件。

## 使用 Time Machine / rollback

1. 打开“时间机器 / Rollback（真实）”。
2. 点击“创建当前安全快照”。
3. 之后如需回退，先查看快照的 diff/stat 预览。
4. 点击“回退到这里”，它会进入确认队列。
5. 在确认队列批准后，才会执行真实 `git reset --hard`。

> 回退前系统会再建一个 `safety` 快照。Rollback 只管本仓库文件，不能撤回外部副作用。

## 本地 API 边界

真实接入：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/wechat/bridge/incoming` | 真实微信桥接入口：写入微信消息并生成 reply_text |
| POST | `/api/wechat/bridge/mark_sent` | 桥接者发回微信后标记 outbox 已发送 |
| POST | `/api/provider/save` | 保存 provider 配置；带 key 时写入 Keychain |
| POST | `/api/provider/check_key` | 检查 Keychain 是否有 key，不读出明文 |
| POST | `/api/provider/delete_key` | 删除 Keychain 中的 key |
| POST | `/api/model/test` | 真实模型调用；必须 `confirm_cost=true` |
| POST | `/api/rollback/snapshot` | 创建真实 git Time Machine 快照 ref |
| GET | `/api/rollback/preview` | 列快照、当前 HEAD、工作区状态、diff 预览 |
| POST | `/api/rollback/request` | 将 rollback 加入确认队列；批准后真实 reset |
| POST | `/api/shougong` | 生成本地收功单 Markdown |
| GET | `/api/health` | 健康检查 |

本地状态/编排记录：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 读本地公开状态，不含明文 key |
| GET | `/api/catalog` | 供应商目录、上限、能力标注 |
| POST | `/api/agent/create` | 本地创建“灵”的状态卡 |
| POST | `/api/task/assign` | 本地记录任务状态；不等于真实 agent runtime |
| POST | `/api/approval/*` | 本地确认队列；rollback approval 会真实执行 git reset |

## 自检

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

`self_check.py` 不会调用真实外部模型 API。它验证：服务能启动、Keychain 行为安全、假 key 不落盘、未确认费用时模型调用会被拒绝、Time Machine 能创建真实 git snapshot 并把 rollback request 加入确认队列、微信桥接端点能收消息/生成 outbox/标记发送。

另有一次隔离临时目录 destructive smoke test，用临时复制仓库验证“批准 rollback 后真实 reset 能删除测试改动”，不会动当前工作仓库。

## 下一阶段优先级

1. **真实 Claude Code worker**：受控目录、权限分级、改码/commit/PR/merge 确认闸。
2. **把微信桥接常驻化**：为当前 LingTai agent 写一个更稳定的 bridge runner/skill，而不是靠手动 curl。
3. **真实 LingTai runtime / mailbox / skills / memory 接入**。
4. **Mac 小应用包装**：不只靠浏览器和命令行。

## 安全原则

- 不保存明文 key。
- 不把未接入能力包装成已可用功能。
- 真实外部副作用必须可见、可确认、可追溯。
- rollback 只能回滚本仓库文件，不能撤回外部副作用。
- 默认 localhost-only。
