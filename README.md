# 圆酱专属轻量版灵台 / LingTai Simple v0.11

这是“傻瓜版灵台 / 圆酱专属轻量版灵台”的本地可运行原型。v0.11 在 v0.10 的真实 Keychain、模型 API、git Time Machine/rollback、微信桥接入口、Claude Code L1-L5、GitHub PR/merge 执行闸、多 agent 编排、洞察、心流基础上，继续往完整 LingTai runtime 接：**Simple 任务现在可以通过 LingTai 内部邮箱真实派发给 `.lingtai/` 网络里的真实 agent**。

## v0.11 新增真实接入

### 1. 真实 LingTai 内部邮箱派发
- `GET /api/lingtai/agents`：只读发现当前 `.lingtai/` 网络里的真实 agent（读取 `.agent.json`）。
- `POST /api/lingtai/dispatch`：把 Simple 本地任务写入 `<sender>/mailbox/outbox/<uuid>/message.json`。
- 默认 sender 为 `human`，可用 `LINGTAI_SIMPLE_MAIL_SENDER` 改；网络目录可用 `LINGTAI_SIMPLE_NETWORK_DIR` 指定。
- 写入后由 LingTai kernel mailman 按内部邮箱协议投递给真实 agent；这不是 mock，会唤醒/占用真实 agent。
- UI 新增“真实 LingTai 派发”大按钮和状态卡；每次派发必须勾选确认。

边界：这一步打通的是 **Simple → LingTai 内部邮箱 → 真实 agent** 的任务入口；它不等于完整 avatar 生命周期管理，也不能保证收件 agent 立即完成任务。真实 agent 完成/卡住后仍按内部邮件回复。

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

自检覆盖：Keychain 不泄露、模型调用未确认会拒绝、任务/确认队列、Time Machine snapshot/request、WeChat bridge、Claude Code L1-L5 守门、多 agent 编排、洞察、心流，以及 **隔离 fake `.lingtai` 网络中的真实 outbox 写入**。

## 仍未完成

- 独立常驻微信 runner（当前仍由现有 LingTai WeChat MCP 桥接，避免双 poller）。
- 完整 LingTai avatar spawn/delete/lull/suspend/CPR 生命周期接入。
- skills / knowledge / molt / soul 的完整 kernel 深度接入。
- Mac app 外壳与安装体验。

原则：没真实接通不说接通；能真实测试的都进 self-check。
