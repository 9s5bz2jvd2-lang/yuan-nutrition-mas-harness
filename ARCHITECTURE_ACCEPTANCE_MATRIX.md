# LingTai Simple 架构验收矩阵（v0.21）

> 原则：**未真实跑通，不写已完成。** 这张表把 `../ARCHITECTURE_EXPERT_DISCUSSION.md` 与圆酱“任何人可从 GitHub 下载运行”的要求逐项拆成验收状态、证据、缺口和测试命令。

状态含义：

- **Done**：已有真实实现，并有自检或 smoke test 证据。
- **Partial**：已有一部分真实链路，但仍有明确缺口；不能宣传成全量完成。
- **Missing**：尚未接入。

| ID | 模块 | 状态 | 已真实跑通的证据 | 仍缺什么 | 验收/测试 |
|---|---|---:|---|---|---|
| A01 | WeChat Gate | Partial | `/api/wechat/bridge/incoming`、`/api/wechat/bridge/mark_sent`、`/api/wechat/bridge/pending`、`/api/wechat/submit`；真实收发由现有 LingTai WeChat MCP 作为唯一桥接者完成，pending outbox 合同明确 `no_second_poller`。 | 尚未提供自治式独立 poller；当前是给现有 LingTai WeChat MCP 使用的本地路由/待发送 outbox 合同。 | `python3 scripts/self_check.py` 覆盖 bridge incoming/pending/mark_sent；真实人工桥接需当前 LingTai WeChat MCP。 |
| A02 | Simple Frontend | Done | 大按钮、本地状态卡、任务停车场、context 压力、模型/API、预算/成本面板、确认队列、收功、Rollback、LingTai runtime、记忆/技能索引均在 `static/`。 | v0 有意不做完整开发者调试台。 | `python3 scripts/self_check.py`；`node --check static/app.js`；浏览器打开 localhost。 |
| A03 | Task Router / Orchestrator | Partial | `/api/task/route` 统一分类普通任务、多 agent、洞察、心流、收功、LingTai mailbox dispatch/collect、Claude/Codex handoff、daemon plan；敏感任务进确认队列。 | v0.21 已补“确认闸 + controller 内部邮箱 + worker_request_id 回信汇总”；Simple 仍不直接启动 daemon/Codex/Claude/avatar，也不绕过既有安全纪律。 | `python3 scripts/self_check.py` 覆盖 `/api/task/route`、WeChat 默认 route_id、fake mailbox dispatch 和 pending outbox。 |
| A04 | Agent Manager | Partial | `MAX_AGENTS=5`；本地 agent 卡片；真实 LingTai agents 发现/绑定/shallow spawn/退休；lull/suspend/interrupt/clear/CPR 确认闸。 | 技能/权限/模型还未完整写入真实 agent init/preset；真实 agent 只安全退休/解绑，不销毁。 | `python3 scripts/self_check.py` 覆盖 fake avatar/lifecycle。 |
| A05 | Model/API Registry | Partial | Provider catalog 含 GPT/OpenAI-compatible、MiMo、DeepSeek、MiniMax、GLM、自定义；Keychain/env/.secrets 受限 fallback 存/取 key；`/api/model/test` 对兼容端点真实调用，需 `confirm_cost`；v0.21 已加 `/api/cost/status`、`/api/cost/policy`、本地价格表、provider 单次 cap、日 cap、任务 cap 与预算预检，越线先生成 `budget_override`。 | MiMo/MiniMax 端点需用户填兼容 base_url；预算/成本仍是本地估算，不连接供应商真实账单/余额，默认价格表需按实际模型校准。 | `python3 scripts/self_check.py` 验证未确认费用拒绝、预算越线确认闸、key 不落盘；真实模型测试需显式确认。 |
| A06 | Secret Vault | Partial | Mac Keychain 通过 Security.framework/ctypes；state/API/log 不回显 key；`/api/health` 与 `/api/secret/scan` 已结构化扫描明文 key 风险且不回显值；self-check 假 key 与临时风险文件验证不落盘/可检测。 | 受限 env/.secrets fallback 已补上；预算预检已与模型调用联动，但不连接供应商真实账单/余额，Secret Vault 侧不做真实扣费来源校验。 | `python3 scripts/self_check.py`；提交前高置信 secret scan。 |
| A07 | Approval Queue | Partial | rollback、delete_agent、sensitive task、Claude L3/L4/L5、LingTai lifecycle/avatar、PR/merge 等进确认队列；UI 显示预览。 | 尚无 allow-once/allow-for-task；日志/截图/报告外发确认未单独做；部分模型调用用 checkbox 而不是队列项。 | `python3 scripts/self_check.py`；隔离 rollback/commit smoke。 |
| A08 | Worker / Sub-agent Pool | Partial | UI 使用普通说法；真实 shallow avatar spawn/bind/retire；Claude Code L1-L5 权限分级与确认闸。 | daemon/Codex/Claude/avatar 类 worker 可从 Simple Task Router 发起受控调度请求并写 controller mailbox；但 Simple 本身仍不直接启动这些 worker，长期助手技能/模型权限也未全量写入真实 agent 配置。 | self-check；Claude Code 真实任务需本机 CLI 和显式确认。 |
| A09 | Memory / Skills / Knowledge / Molt | Done | v0.17 起只读索引真实 pad/knowledge/custom skills/shared skills/summaries；`/api/shougong` 生成阶段成果、未竟事项、下一步、路径与风险。 | 目前只读；写回 knowledge/skills/molt 仍交给真实 LingTai agent 流程。 | `python3 scripts/self_check.py` 覆盖 fake durable stores 和 secrets 拒读。 |
| A10 | Rollback / Time Machine | Done | `/api/rollback/snapshot`、preview、request；批准后真实 `git reset --hard`，先写 safety ref；UI/README 标明外部副作用不可回滚。 | 只覆盖本仓库 tracked/unignored 文件。 | self-check + 隔离 `/tmp` destructive rollback smoke。 |
| A11 | GitHub downloadable/runnable | Done | `run.sh`、`QUICKSTART.md`、README clone/ZIP 运行；ZIP-like 无 `.git` 也能启动核心 UI。 | 高级能力仍需本机工具/配置；Quickstart 已说明。 | `rsync --exclude .git` 到 `/tmp` 后 `./run.sh`，`/api/health` ok。 |

## 下一批优先实现

1. **受控 worker 直连执行深化**：v0.21 已完成 controller mailbox + 回信汇总；下一步若要更进一步，可让 controller 侧形成标准执行协议/模板，减少人工解释。
2. **预算/成本校准**：当前为本地估算；后续按实际 provider/model 校准价格表，并在可用时接只读账单/余额查询。

## 机器可读状态

本矩阵也暴露为本地 API：

```bash
curl http://127.0.0.1:8765/api/architecture/status
```

前端入口：打开本地 UI 后点击 **“📋 架构验收表”**。
