# 圆酱专属轻量版灵台 / LingTai Simple v0.2 — 大按钮原型

一个**本地可运行**的「傻瓜版灵台」原型：普通人一眼能懂的大按钮界面，围绕圆酱的真实需求（微信入口、最多 5 个灵、模型/API 中心、Claude Code 代码苦力、确认队列、收功、时间机器）。

> ⚠️ 这是 **v0 原型**：**所有高危动作都是 mock**。不外发、不真实改码、不真实 rollback、不回显 key。

---

## v0.2 更新

- GUI 已改成圆酱指定的**低饱和度粉蓝色**：雾面浅蓝底、低饱和粉紫主色、柔和蓝色按钮与卡片。
- 新增「加载示例状态」「健康检查」「怎么看这个原型」三个快速体验入口。
- 新增 Mac 双击启动文件：`启动圆酱灵台.command`。
- 新增 `scripts/self_check.py` 本地自检脚本。

---

## 1. 如何运行

只需要 Python 3（标准库，**零第三方依赖**）。

```bash
git clone https://github.com/9s5bz2jvd2-lang/yuanjiang-lingtai-simple.git
cd yuanjiang-lingtai-simple
python3 server.py
```

然后浏览器打开：**http://127.0.0.1:8765/**

自定义端口/地址（默认 localhost）：

```bash
LINGTAI_SIMPLE_PORT=8771 python3 server.py
```

停止：`Ctrl+C`。

---

## 2. 界面里有什么（大按钮）

| 大按钮 | 作用 |
|---|---|
| 🌱 新建一个灵 | 起名、选角色（长期助手/临时分析/代码苦力）、选模型、设 Claude Code 权限等级。最多 5 个。 |
| 📨 给灵派任务 | 一句话派活。普通任务自动 mock 完成；敏感任务进确认队列。 |
| 💬 微信入口任务 | 模拟「微信发一句话」：自动 ACK → 排队 → 执行 → 完成；含敏感关键词自动进确认队列。 |
| 🧠 模型 / API 中心 | GPT/OpenAI-compatible、小米 MiMo、DeepSeek、MiniMax、GLM/智谱、自定义。只显示「已配置」+ 后四位。 |
| 🛠️ Claude Code 苦力 | 只读分析 / 本地改码 / commit / PR / merge 权限分级；merge 必须显式确认。 |
| ✅ 确认队列 | 外发/改码/PR/merge/rollback/删除 等敏感动作先 preview，再确认或拒绝。 |
| 📋 一键收功 | 生成 Markdown 收功单（已完成/未完成/待确认/灵状态/下一步），存到 `data/shougong/`。 |
| ⏪ 时间机器 / 回退 | 只 mock 列 snapshot 和 diff；点回退仅进确认队列预览，**不真实 reset**。 |

页面还包含：**灵状态卡**、**任务停车场**、**context 压力条**、**事件日志（脱敏）**。

---

## 3. 哪些是 mock（边界）

**全部高危动作都不会产生真实副作用：**

- ❌ 不真实发送微信 / 邮件 / Telegram —— 只生成 preview。
- ❌ 不真实调用任何模型 API（GPT/MiMo/DeepSeek/MiniMax/GLM 等）。
- ❌ 不真实调用 Claude Code，不真实 commit/push/PR/merge。
- ❌ 不真实 rollback / git reset。
- ❌ 不访问外网。服务默认绑定 `127.0.0.1`，并在请求层拒绝非本机来源。

**凭证安全：**

- 不保存明文 API key。输入 key 只用于提取**后四位**展示，后端保存 `configured: true` + `key_last4` + 可选 `key_label`。
- 界面不回显明文 key；日志/收功单/API 响应自动脱敏（`sk-...`、长 token、`Bearer ...` → `****REDACTED****`）。
- 已验证：`data/state.json` 中不含任何明文 key。

---

## 4. 文件结构

```
yuanjiang-lingtai-simple/
├── README.md                  # 本文件
├── IMPLEMENTATION_REPORT.md   # 做了什么 / 如何验证 / 限制
├── server.py                  # 本地 stdlib HTTP 服务 + 状态/API
├── static/
│   ├── index.html             # 大按钮 UI
│   ├── styles.css             # 温暖但清晰的中文界面
│   └── app.js                 # 前端逻辑（原生 JS，无依赖）
└── data/
    ├── state.json             # 运行时状态（首启动自动创建）
    ├── state.example.json     # 示例数据（参考用）
    └── shougong/              # 生成的收功单 Markdown
```

---

## 5. 最小后端 API（本地）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/state` | 读取公开状态（供应商不含任何 key） |
| GET | `/api/catalog` | 供应商目录 + CC 权限等级 + 上限 |
| POST | `/api/agent/create` | 新建灵（≤5） |
| POST | `/api/task/assign` | 派任务（敏感→确认队列） |
| POST | `/api/agent/pause` `/resume` `/delete` | 暂停/恢复/删除（删除走确认队列） |
| POST | `/api/approval/add` `/approve` `/deny` | 确认队列增/确认/拒绝 |
| POST | `/api/provider/save` | 保存供应商配置（脱敏，不存明文 key） |
| POST | `/api/wechat/submit` | 微信任务入队（mock ACK/执行） |
| POST | `/api/shougong` | 生成收功单 Markdown |
| GET | `/api/rollback/preview` · POST `/api/rollback/request` | 快照预览 / 回退请求（进确认队列，不真实 reset） |
| POST | `/api/cc/request` | Claude Code 苦力任务（按等级走确认队列） |
| POST | `/api/reset` | 重置原型数据 |

---

## 6. 下一步（v0 之后）

1. 接真实 LingTai mailbox / WeChat addon（仍走主控路由 + 确认队列）。
2. Secret Vault 升级为 Mac Keychain，启动时扫描明文 key 风险并提示迁移。
3. 接真实 Claude Code worker（受控 worktree，权限分级，merge 永远显式确认）。
4. 接 PR #228 Time Machine 真实 snapshot（仍二次确认，标注不可撤回外部副作用）。
5. 成熟后把稳定组件回流 LingTai Portal 的 Simple mode。

> 本原型**不修改 LingTai 主仓库源码**；代码内所有高危动作仍为 mock/preview。

---

## 7. Claude Code 安全复检

推送前已让 Claude Code 做只读安全复检，结论为：**SAFE TO PUSH，无阻断项**。详见 [`CLAUDE_CODE_REVIEW.md`](CLAUDE_CODE_REVIEW.md)。
