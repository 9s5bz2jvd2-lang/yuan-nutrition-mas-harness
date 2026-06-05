# 圆酱专属轻量版灵台 / LingTai Simple v0.3

> **原则：本页只把已经真实接入的能力当成功能。未接入能力必须灰显或写进“下一步”，不再用 mock 冒充能用。**

这是“傻瓜版灵台”的本地可运行原型。v0.3 的目标不是把所有灵台能力一次性做完，而是把第一批真实能力接进去，并把还没接入的能力诚实标出来。

## v0.3 已真实接入

1. **Mac Keychain 密钥保险柜**
   - API Key 写入 macOS 系统 Keychain。
   - `state.json`、日志、接口响应不保存明文 key。
   - 当前实现通过 macOS `Security.framework`（Python `ctypes`）调用 Keychain，不把 key 放进 shell 命令参数。
   - Keychain 不可用或系统拒绝时直接报错，不退化成明文存储。

2. **真实模型 API 调用**
   - 支持 OpenAI-compatible `/chat/completions`。
   - UI 必须显式点击“运行真实模型测试”，并勾选“可能产生费用”，才会发起网络请求。
   - 单次测试有超时和 token 上限，避免误烧钱。
   - 支持配置：GPT/OpenAI-compatible、DeepSeek、GLM/智谱、自定义 base_url+model；小米 MiMo、MiniMax 先保留为可填写自定义兼容端点，不硬编未核验 URL。

3. **本地 GUI / 状态管理**
   - 大按钮界面、最多 5 个“灵”的本地状态卡。
   - 本地任务停车场、确认队列、一键收功 Markdown、健康检查。
   - 这些是本地编排/记录能力，不等于已经接入真实灵台 runtime。

## v0.3 尚未真实接入（不算完成功能）

这些能力是圆酱明确需要的，但 v0.3 里还没接入真实执行链，所以页面已灰显或标成下一阶段：

- **微信 bot 指令入口**：必须像当前灵台一样，圆酱在微信发指令 → 系统收任务 → 派活 → 结果回微信。下一阶段优先接。
- **Claude Code 真实苦力**：受控 worktree、权限分级、本地改码、commit、PR、merge。下一阶段接入；merge 必须显式确认。
- **真实 commit/push/PR/merge**：目前不从此应用执行。
- **真实 rollback / Time Machine**：等待接 LingTai rollback PR 能力后再做，仍需二次确认。
- **微信 / 邮件 / Telegram 外发**：未接入真实外发，不当成功能展示。

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

## 使用 v0.3 的真实模型 API

1. 打开“模型 / API 中心”。
2. 选择供应商，填写 `base_url`、`model`、API key。
3. 保存后，key 会进入 Mac Keychain；界面只显示“已配置”和后四位。
4. 勾选“我已知道这是真实调用、可能产生费用”。
5. 点击“运行真实模型测试”。

> 如果 Keychain 被系统拒绝（例如无交互 session、钥匙串锁定），保存 key 会失败；这是安全失败，不会把 key 写到 JSON 文件。

## 本地文件结构

```text
yuanjiang-lingtai-simple/
├── README.md
├── IMPLEMENTATION_REPORT.md
├── CLAUDE_CODE_REVIEW.md          # v0.2 推送前 Claude Code 安全复检记录
├── server.py                      # 本地 HTTP 服务 + Keychain + OpenAI-compatible 调用
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/
│   ├── self_check.py              # 本地自检；不调用真实外部模型
│   └── load_demo.py
└── data/
    ├── state.example.json
    └── shougong/                  # 运行时生成，git 忽略
```

## 本地 API 边界

真实接入：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/provider/save` | 保存 provider 配置；带 key 时写入 Keychain |
| POST | `/api/provider/check_key` | 检查 Keychain 是否有 key，不读出明文 |
| POST | `/api/provider/delete_key` | 删除 Keychain 中的 key |
| POST | `/api/model/test` | 真实模型调用；必须 `confirm_cost=true` |
| POST | `/api/shougong` | 生成本地收功单 Markdown |
| GET | `/api/health` | 健康检查 |

本地状态/编排记录：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 读本地公开状态，不含明文 key |
| GET | `/api/catalog` | 供应商目录、上限、能力标注 |
| POST | `/api/agent/create` | 本地创建“灵”的状态卡 |
| POST | `/api/task/assign` | 本地记录任务状态；不等于真实 agent runtime |
| POST | `/api/approval/*` | 本地确认队列记录 |

未接入真实执行链的旧端点若保留，仅供历史/内部占位，不应当在主界面当成功能展示。

## 自检

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

`self_check.py` 不会调用真实外部模型 API。它只验证：服务能启动、Keychain 行为安全、假 key 不落盘、未确认费用时模型调用会被拒绝。

## 下一阶段优先级

1. **真实微信 bot 指令入口**：圆酱微信发指令 → 轻量版灵台收任务 → 派给模型/子灵/Claude Code → 回微信。
2. **真实 Claude Code worker**：受控目录、权限分级、改码/commit/PR/merge 确认闸。
3. **Mac 小应用包装**：不是只靠浏览器和命令行。
4. **真实 LingTai runtime / mailbox / skills / memory 接入**。
5. **Time Machine / rollback 接入**：只在二次确认后执行。

## 安全原则

- 不保存明文 key。
- 不把未接入能力包装成已可用功能。
- 真实外部副作用必须可见、可确认、可追溯。
- 默认 localhost-only。
