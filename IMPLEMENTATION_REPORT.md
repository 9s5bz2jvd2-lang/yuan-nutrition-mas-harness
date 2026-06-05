# 实现报告 / Implementation Report

**项目**：圆酱专属轻量版灵台 / LingTai Simple v0.2 — 大按钮原型
**日期**：2026-06-05
**目录**：`projects/lingtai_simple_20260605/simple_prototype/`
**授权范围**：仅本地原型代码实现。**未** commit/push/PR/merge；**未**修改 LingTai 主仓库源码。

---

## 1. 做了什么

按 `ARCHITECTURE_EXPERT_DISCUSSION.md` / `EXCLUSIVE_FEASIBILITY_COMBINED_FOR_RUNYUAN.md` / `STATUS_20260605.md` 的 v0 设计，实现了一个**本地可打开的大按钮 Web 原型**：

- **技术栈**：纯 Python 3 标准库（`http.server` + `json`）+ 静态 HTML/CSS/JS。**零第三方依赖**，无需 pip install。
- **后端** `server.py`：localhost-only HTTP 服务，本地 JSON 状态读写，约 15 个 API。
- **前端** `static/`：中文、温暖但清晰、大按钮卡片式界面，原生 JS（无框架）。
- **数据** `data/`：运行时 `state.json`（自动创建）、`state.example.json`（示例）、`shougong/`（收功单输出）。

### 已实现的大按钮 / 卡片（对照需求清单全部覆盖）

| 需求 | 状态 |
|---|---|
| 新建一个灵（≤5，名字/角色/模型/CC 权限） | ✅ |
| 给灵派任务 | ✅ |
| 暂停 / 恢复 / 删除灵（删除走确认队列） | ✅ |
| 模型/API 中心（GPT/MiMo/DeepSeek/MiniMax/GLM/自定义；只显示已配置，不回显 key） | ✅ |
| 微信入口任务队列（ACK→排队→执行→完成，敏感进确认） | ✅ |
| 确认队列（preview + 确认/拒绝） | ✅ |
| Claude Code 苦力卡（只读/改码/commit/PR/merge 分级；merge 显式确认） | ✅ |
| 一键收功（生成 Markdown） | ✅ |
| Rollback / Time Machine preview（只 mock 列 snapshot/diff，不真实 reset） | ✅ |
| context 压力条 / agent 状态卡 / 任务停车场 | ✅ |
| 事件日志（脱敏） | ✅（额外） |

---

## 2. 安全设计落点（硬红线）

- **localhost-only**：默认绑定 `127.0.0.1`；请求处理层 `_guard_local()` 拒绝非本机来源（403）。
- **不外发 / 不真实执行**：微信/邮件/Telegram/commit/PR/merge/rollback/API 调用全部为 mock，只产生 preview，敏感动作强制进确认队列。
- **凭证安全**：
  - 输入的 API key 只用于提取**后四位**，后端从不持久化明文（`save_provider` 不写 `api_key` 字段）。
  - 公开状态 `_public_state()` 防御性 `pop("api_key")`。
  - 全局 `redact()` 对 `sk-...` / 32+ 长串 / `Bearer ...` 脱敏，应用于日志、收功单、任务描述。
  - 日志打印（`log_message`）也经过脱敏。
- **≤5 个灵**：`create_agent` 硬上限。
- **merge 必须显式确认**：CC level 5 永远进确认队列。

---

## 3. 如何验证（已执行的自检）

环境：macOS，Python 3.14.5。测试端口 8771。

```
1. 语法检查：python3 -m py_compile server.py        → SYNTAX_OK
2. GET /                                            → 200
3. GET /api/catalog                                → providers 6, cc_levels 5, max 5
4. POST /api/agent/create                          → ok, agent_count 1
5. POST /api/provider/save (带 key)                → configured True, last4 WXYZ, 状态中无 api_key 字段
6. grep 明文 key in data/state.json                → NO_PLAINTEXT_KEY_OK（0 命中）
7. POST /api/task/assign (sensitive)               → task_status 等确认, pending_approvals 1
8. POST /api/approval/approve                       → ok, pending_approvals 0
9. POST /api/wechat/submit (低风险, 有空闲灵)       → 完成, 阶段 已收到→排队中→执行中→完成
10. POST /api/cc/request level=1                    → 只读分析直接 mock 完成
11. POST /api/cc/request level=5 (merge)            → queued True（进确认队列）
12. POST /api/rollback/request                      → action rollback_apply（进确认队列）
13. POST /api/shougong                              → 生成 shougong_*.md (543 bytes)
14. GET 未知路由                                    → 404
15. state.example.json                              → agents 2, providers 1, wx 1
```

全部通过。服务可稳定启动并响应。

### 复现方式

```bash
cd simple_prototype
python3 server.py          # 启动
# 浏览器打开 http://127.0.0.1:8765/
```

---

## 4. 限制 / 已知边界

1. **全部是 mock**：不产生任何真实副作用（这是 v0 的安全前提，不是缺陷）。
2. **Secret Vault 简化版**：当前用本地 JSON 存「configured + 后四位」；未接 Mac Keychain（列入下一步）。明文 key 输入后只在内存中用于取后四位，不落盘——但仍建议未来用 Keychain 彻底隔离。
3. **localhost 守卫基于 client_address**：足够防止局域网/公网直连；不替代完整鉴权，v0 默认单用户本机。
4. **状态损坏自动重置**：`state.json` 解析失败会重建（原型容错，生产需更稳妥的恢复）。
5. **未接真实 LingTai runtime**：mailbox / WeChat addon / Claude Code worker / PR #228 Time Machine 均为占位 mock，接入是 v0 之后的工作。
6. **轮询刷新**：前端每 5s 拉一次状态（无 WebSocket），原型够用。

---

## 5. 交付清单

- `README.md` — 运行方式、边界、mock 范围、下一步
- `server.py` — 本地服务 + API + 状态管理 + 脱敏
- `static/index.html` / `static/styles.css` / `static/app.js` — 大按钮 UI
- `data/state.example.json` — 示例状态
- `data/shougong/` — 收功单输出目录
- `IMPLEMENTATION_REPORT.md` — 本报告

**未做（遵守授权）**：未 commit/push/PR/merge，未改主仓源码，未真实发微信。

---

## 6. GUI 优先级修正（圆酱补充）

圆酱补充：**「大按钮某种意义上其实就是 GUI 界面」**。据此确认 v0 的核心交付不是后端 API，而是**普通人能打开、能点、能看状态的图形界面**。

落点确认（已满足）：

- `static/index.html` + `styles.css` + `app.js` 构成完整可交互 GUI：顶部一排大按钮 + 卡片网格。
- 每个大按钮都有真实弹层/表单/列表交互（不是占位）：新建灵、派任务、微信入口、模型/API 中心、Claude Code 苦力、确认队列、一键收功、时间机器预览。
- 子灵状态卡、任务停车场、确认卡（含 preview）、context 压力条、事件日志实时渲染（每 5s 轮询刷新）。
- 视觉为中文、温暖但清晰，一眼像「轻量版灵台」。
- 底层全部 mock；**仍不真实外发 / 不真实 API / 不真实 rollback / 不 commit/push/PR/merge**。

## 7. 最终独立复验（本轮，端口 8801，全新启动）

在清空运行时数据后，从零启动当前磁盘上的 `server.py` 再次复验：

```
GET /            → 200
GET /styles.css  → 200
GET /api/state   → agents 0（干净启动）
POST agent/create→ ok=True
POST shougong    → 生成 shougong_*.md
server stderr    → 空（无报错）
data/state.json 中无明文 key（grep 命中 0）
```

`server.py` 通过 `ast.parse` 语法检查；`static/app.js` 通过 `node --check`。结论：**可从零稳定启动并响应，凭证不落盘明文。**


---

## v0.2 追加完善

- 按圆酱要求把界面改为低饱和度粉蓝色。
- 增加快速体验区：加载示例状态、健康检查、查看说明。
- 增加 Mac 双击启动入口 `启动圆酱灵台.command`。
- 增加 `scripts/self_check.py` 与 `scripts/load_demo.py`。
- 修复权限等级解析兼容：支持 `1` / `"1"` / `"L1"`。
