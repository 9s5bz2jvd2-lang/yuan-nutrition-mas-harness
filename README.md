# 圆酱专属轻量版灵台 / LingTai Simple v0.10

这是“傻瓜版灵台 / 圆酱专属轻量版灵台”的本地可运行原型。v0.10 在 v0.9 的真实 Keychain、模型 API、git Time Machine/rollback、微信桥接入口、Claude Code L1-L5、GitHub PR/merge 执行闸基础上，补上圆酱指出的三块“灵台味”核心：**多 agent / 子灵编排、洞察、心流**。

## v0.10 已真实接入

### 1. 多 agent / 子灵编排（本地真实状态）
- `POST /api/agent/orchestrate`
- 可选择已有子灵，也可自动创建：主控洞察灵、执行落地灵、审校回环灵。
- 会把一个目标拆成多条子任务，写入 `orchestrations[]` 和 `tasks[]`，并同步生成一条洞察。
- 微信桥接可触发：`多agent <目标>`。

边界：这是本地编排与状态落盘，不假装每个子灵已经独立跑完外部模型或完整 LingTai runtime。

### 2. 洞察（本地状态分析）
- `POST /api/insight/generate`
- 读取当前子灵、任务、确认队列、卡点、context 压力和敏感动作，生成 `insights[]`。
- 微信桥接可触发：`洞察` 或 `洞察 <焦点>`。

边界：v0.10 洞察是确定性本地规则分析，不调用外部模型、不产生费用。

### 3. 心流（阶段回环）
- `POST /api/soul/flow`
- 把当前任务、最近洞察、确认队列和上下文压力收束成一条可追踪心流记录，写入 `soul_flows[]`。
- 微信桥接可触发：`心流` 或 `心流 <触发原因>`。

边界：这是 LingTai Simple 内的轻量心流记录；后续还要接完整 LingTai soul/memory runtime。

### 4. 继续保留的真实能力
- Mac Keychain 密钥保险柜：API key 不落 JSON / 日志 / 响应。
- OpenAI-compatible 真实模型 API 调用：必须显式确认费用。
- git Time Machine / rollback：snapshot、preview、确认后真实 `git reset --hard`。
- WeChat bridge endpoint：不启动第二个 poller，由当前 LingTai WeChat MCP 作为唯一真实收发桥。
- Claude Code L1 只读分析、L2 本地改码、L3 本地 commit、L4 GitHub PR、L5 GitHub merge：全部走确认/安全闸。

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
python3 scripts/self_check.py
```

自检覆盖：Keychain 不泄露、模型调用未确认会拒绝、任务/确认队列、Time Machine snapshot/request、WeChat bridge、Claude Code L1-L5 守门、多 agent 编排、洞察、心流。

## 仍未完成

- 独立常驻微信 runner（当前仍由现有 LingTai WeChat MCP 桥接，避免双 poller）。
- 完整 LingTai runtime / mailbox / skills / knowledge / molt / soul 深度接入。
- Mac app 外壳与安装体验。

原则：没真实接通不说接通；能真实测试的都进 self-check。
