# 圆酱专属轻量版灵台 / LingTai Simple v0.4

> **原则：只把已经真实接入、可验证的能力写成“已完成”。未接入能力必须灰显或写进“下一步”，不再用 mock 冒充能用。**

这是“傻瓜版灵台”的本地可运行原型。v0.4 在 v0.3 的 Keychain + 真实模型 API 基础上，继续接入了 **真实 git Time Machine / rollback**：可以创建安全快照、预览 diff，并在确认队列批准后执行真实 `git reset --hard` 回退。

## v0.4 已真实接入

1. **Mac Keychain 密钥保险柜**
   - API Key 写入 macOS 系统 Keychain。
   - `state.json`、日志、接口响应不保存明文 key。
   - 通过 macOS `Security.framework` + Python `ctypes` 调用 Keychain，不把 key 放进 shell 命令参数。
   - Keychain 不可用或系统拒绝时直接报错，不退化成明文存储。

2. **真实模型 API 调用**
   - 支持 OpenAI-compatible `/chat/completions`。
   - UI 必须显式点击“运行真实模型测试”，并勾选“可能产生费用”，才会发起网络请求。
   - 单次测试有 timeout 与 token 上限，避免误烧钱。
   - 支持配置：GPT/OpenAI-compatible、DeepSeek、GLM/智谱、自定义 `base_url + model`；小米 MiMo、MiniMax 先保留为可填写自定义兼容端点，不硬编未核验 URL。

3. **git Time Machine / rollback（真实本地副作用）**
   - `POST /api/rollback/snapshot`：把当前工作树创建为 git 安全快照 ref（不移动当前分支）。
   - `GET /api/rollback/preview`：列出 snapshot/safety refs，展示当前 HEAD、工作区状态、到快照的 diff/stat 预览。
   - `POST /api/rollback/request`：把目标快照加入确认队列。
   - 批准确认队列后：执行真实 `git reset --hard <snapshot_commit>`。
   - 执行 reset 前会自动创建 safety ref，方便找回 reset 前状态。
   - 边界：只能回滚本仓库文件；不能撤回已发微信/邮件/API 请求/PR/merge 等外部副作用；被 `.gitignore` 忽略的运行时文件（如 `data/state.json`）不作为代码快照核心目标。

4. **本地 GUI / 状态管理**
   - 大按钮界面、最多 5 个“灵”的本地状态卡。
   - 本地任务停车场、确认队列、一键收功 Markdown、健康检查。
   - 这些仍是本地编排/记录能力，不等于已经接入完整 LingTai runtime。

## v0.4 尚未真实接入（不算完成功能）

这些能力是圆酱明确需要的，但 v0.4 里还没接入真实执行链，所以页面继续灰显或标成下一阶段：

- **微信 bot 指令入口**：必须像当前灵台一样，圆酱在微信发指令 → 系统收任务 → 派活 → 结果回微信。下一阶段优先接。
- **Claude Code 真实苦力**：受控 worktree、权限分级、本地改码、commit、PR、merge。merge 必须显式确认。
- **真实 commit/push/PR/merge**：目前不从此应用执行。
- **微信 / 邮件 / Telegram 外发**：未接入真实外发，不当成功能展示。
- **Mac 小应用外壳**：当前仍是 localhost Web + 双击启动脚本。

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

`self_check.py` 不会调用真实外部模型 API。它验证：服务能启动、Keychain 行为安全、假 key 不落盘、未确认费用时模型调用会被拒绝、Time Machine 能创建真实 git snapshot 并把 rollback request 加入确认队列。

另有一次隔离临时目录 destructive smoke test，用临时复制仓库验证“批准 rollback 后真实 reset 能删除测试改动”，不会动当前工作仓库。

## 下一阶段优先级

1. **真实微信 bot 指令入口**：圆酱微信发指令 → 轻量版灵台收任务 → 派给模型/子灵/Claude Code → 回微信。
2. **真实 Claude Code worker**：受控目录、权限分级、改码/commit/PR/merge 确认闸。
3. **真实 LingTai runtime / mailbox / skills / memory 接入**。
4. **Mac 小应用包装**：不只靠浏览器和命令行。

## 安全原则

- 不保存明文 key。
- 不把未接入能力包装成已可用功能。
- 真实外部副作用必须可见、可确认、可追溯。
- rollback 只能回滚本仓库文件，不能撤回外部副作用。
- 默认 localhost-only。
