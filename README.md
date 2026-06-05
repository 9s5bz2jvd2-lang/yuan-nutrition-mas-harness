# 圆酱专属轻量版灵台 / LingTai Simple v0.12

这是“傻瓜版灵台 / 圆酱专属轻量版灵台”的本地可运行原型。v0.12 在 v0.11 的真实 LingTai 内部邮箱派发入口基础上继续往完整 LingTai runtime 接：**现在可以只读回收真实 agent 的内部邮件回复，并把 lull / suspend / interrupt / clear / CPR 等生命周期动作放入确认队列，确认后才写真实 signal 或尝试复苏。**

## v0.12 新增真实接入

### 1. 真实 agent 回复回收
- `POST /api/lingtai/collect`：只读扫描 `<reply_inbox>/mailbox/inbox/*/message.json`，默认 reply inbox 为 `mimo-2-5-pro`，可用 `LINGTAI_SIMPLE_REPLY_INBOX` 修改。
- 回收逻辑会按原派发 mailbox id、sender、subject 匹配 `lingtai_dispatches`，把回复写入 `lingtai_mail_results`。
- 匹配成功后会把对应 dispatch 标记为 `reply_received`，并把本地任务状态更新为“完成”，结果预览显示真实回信摘要。
- 该操作**不删除、不移动、不标记已读**真实 LingTai 邮箱；只是读入 Simple 状态，避免破坏 kernel 邮箱。

### 2. 生命周期动作确认闸
- `POST /api/lingtai/lifecycle/request`：支持 `lull` / `suspend` / `interrupt` / `clear` / `cpr`，先进入确认队列，不会立即执行。
- 批准后：
  - `lull` 写 `.sleep` signal；
  - `suspend` 写 `.suspend` signal；
  - `interrupt` 写 `.interrupt` signal；
  - `clear` 写 `.clear` signal；
  - `cpr` 在目标 heartbeat 不新鲜且有 `init.json` 时，用 `lingtai-agent run <agent_dir>` 尝试复苏。
- UI 增加“回收真实 agent 回复”和“生命周期动作”按钮；所有生命周期动作都必须确认。

边界：v0.12 仍不是完整 avatar 管理器；不会做文件删除，也不提供 nirvana。`clear` 会影响真实 agent 上下文，CPR 会尝试启动真实进程，所以必须走确认队列。

## 已真实接入能力总表

- Mac Keychain 密钥保险柜：API key 不落 JSON / 日志 / 响应。
- OpenAI-compatible 真实模型 API 调用：必须显式确认费用。
- git Time Machine / rollback：snapshot、preview、确认后真实 `git reset --hard`。
- WeChat bridge endpoint：不启动第二个 poller，由当前 LingTai WeChat MCP 作为唯一真实收发桥。
- Claude Code：L1 只读分析、L2 本地改码、L3 本地 commit、L4 GitHub PR、L5 GitHub merge，全部走确认/安全闸。
- 多 agent / 子灵编排：`POST /api/agent/orchestrate`，创建/选择子灵、拆任务、记录批次。
- 洞察：`POST /api/insight/generate`，本地状态分析。
- 心流：`POST /api/soul/flow`，阶段回环记录。
- 真实 LingTai 内部邮箱派发：`POST /api/lingtai/dispatch`。
- 真实 LingTai 回复回收：`POST /api/lingtai/collect`。
- 真实 LingTai 生命周期确认闸：`POST /api/lingtai/lifecycle/request` → approve 后写 signal / CPR。

## 运行

```bash
cd /Users/huangzesen/work/projects/runyuan_wang/.lingtai/mimo-2-5-pro/projects/lingtai_simple_20260605/yuanjiang-lingtai-simple-repo
python3 server.py
# 打开 http://127.0.0.1:8765/
```

也可双击：`启动圆酱灵台.command`。

## 自检

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
node --check static/app.js
python3 scripts/self_check.py
```

自检覆盖：Keychain 不泄露、模型调用未确认会拒绝、任务/确认队列、Time Machine snapshot/request、WeChat bridge、Claude Code L1-L5 守门、多 agent 编排、洞察、心流、隔离 fake `.lingtai` 网络中的真实 outbox 写入、fake reply inbox 中的真实回信回收、生命周期动作只进入确认队列。

## 仍未完成

- 独立常驻微信 runner（当前仍由现有 LingTai WeChat MCP 桥接，避免双 poller）。
- 完整 LingTai avatar spawn / delete 管理；v0.12 只做到既有 agent 发现、派发、回复回收、确认后 signal/CPR。
- skills / knowledge / molt / soul 的完整 kernel 深度接入。
- Mac app 外壳与安装体验。

原则：没真实接通不说接通；能真实测试的都进 self-check。
