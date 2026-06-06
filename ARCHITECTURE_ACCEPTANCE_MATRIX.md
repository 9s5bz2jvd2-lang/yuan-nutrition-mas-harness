# LingTai Simple 架构验收矩阵（v0.16）

> 原则：**未真实跑通，不写已完成。** 这张表把 `../ARCHITECTURE_EXPERT_DISCUSSION.md` 与圆酱“任何人可从 GitHub 下载运行”的要求逐项拆成验收状态、证据、缺口和测试命令。

状态含义：

- **Done**：已有真实实现，并有自检或 smoke test 证据。
- **Partial**：已有一部分真实链路，但仍有明确缺口；不能宣传成全量完成。
- **Missing**：尚未接入。

| ID | 模块 | 状态 | 已真实跑通的证据 | 仍缺什么 | 验收/测试 |
|---|---|---:|---|---|---|
| A01 | WeChat Gate | Partial | `/api/wechat/bridge/incoming`、`/api/wechat/bridge/mark_sent`、`/api/wechat/submit`；真实收发由现有 LingTai WeChat MCP 作为唯一桥接者完成，避免第二 poller。 | 尚未提供独立常驻 bridge runner；自动 ACK 阶段状态仍以 bridge 返回文本/本地状态为主。 | `python3 scripts/self_check.py` 覆盖 bridge endpoint；人工桥接需当前 LingTai WeChat MCP。 |
| A02 | Simple Frontend | Done | 大按钮、本地状态卡、任务停车场、context 压力、模型/API、确认队列、收功、Rollback、LingTai runtime、记忆/技能索引均在 `static/`。 | v0 有意不做完整开发者调试台。 | `python3 scripts/self_check.py`；`node --check static/app.js`；浏览器打开 localhost。 |
| A03 | Task Router / Orchestrator | Partial | `/api/task/assign`、`/api/agent/orchestrate`、洞察、心流、收功、LingTai mailbox dispatch/collect；敏感任务进确认队列。 | 尚未全自动统一调度 daemon/Codex/Claude/real avatar 并自动汇总回微信。 | `python3 scripts/self_check.py` 覆盖本地编排与 fake mailbox。 |
| A04 | Agent Manager | Partial | `MAX_AGENTS=5`；本地 agent 卡片；真实 LingTai agents 发现/绑定/shallow spawn/退休；lull/suspend/interrupt/clear/CPR 确认闸。 | 技能/权限/模型还未完整写入真实 agent init/preset；真实 agent 只安全退休/解绑，不销毁。 | `python3 scripts/self_check.py` 覆盖 fake avatar/lifecycle。 |
| A05 | Model/API Registry | Partial | Provider catalog 含 GPT/OpenAI-compatible、MiMo、DeepSeek、MiniMax、GLM、自定义；Keychain 存 key；`/api/model/test` 对兼容端点真实调用，需 `confirm_cost`；单次 timeout/max_tokens 上限。 | MiMo/MiniMax 端点需用户填兼容 base_url；尚无累计预算/价格表/余额估算。 | self-check 验证未确认费用拒绝、key 不落盘；真实模型测试需显式确认。 |
| A06 | Secret Vault | Partial | Mac Keychain 通过 Security.framework/ctypes；state/API/log 不回显 key；self-check 假 key 验证不落盘。 | 尚无受限 `.secrets`/env fallback；启动明文 key 风险扫描未结构化进 health。 | `python3 scripts/self_check.py`；提交前高置信 secret scan。 |
| A07 | Approval Queue | Partial | rollback、delete_agent、sensitive task、Claude L3/L4/L5、LingTai lifecycle/avatar、PR/merge 等进确认队列；UI 显示预览。 | 尚无 allow-once/allow-for-task；日志/截图/报告外发确认未单独做；部分模型调用用 checkbox 而不是队列项。 | `python3 scripts/self_check.py`；隔离 rollback/commit smoke。 |
| A08 | Worker / Sub-agent Pool | Partial | UI 使用普通说法；真实 shallow avatar spawn/bind/retire；Claude Code L1-L5 权限分级与确认闸。 | daemon/Codex worker 尚未从 Simple UI/API 发起；长期助手技能/模型权限未全量写入真实 agent 配置。 | self-check；Claude Code 真实任务需本机 CLI 和显式确认。 |
| A09 | Memory / Skills / Knowledge / Molt | Done | v0.16 起只读索引真实 pad/knowledge/custom skills/shared skills/summaries；`/api/shougong` 生成阶段成果、未竟事项、下一步、路径与风险。 | 目前只读；写回 knowledge/skills/molt 仍交给真实 LingTai agent 流程。 | `python3 scripts/self_check.py` 覆盖 fake durable stores 和 secrets 拒读。 |
| A10 | Rollback / Time Machine | Done | `/api/rollback/snapshot`、preview、request；批准后真实 `git reset --hard`，先写 safety ref；UI/README 标明外部副作用不可回滚。 | 只覆盖本仓库 tracked/unignored 文件。 | self-check + 隔离 `/tmp` destructive rollback smoke。 |
| A11 | GitHub downloadable/runnable | Done | `run.sh`、`QUICKSTART.md`、README clone/ZIP 运行；ZIP-like 无 `.git` 也能启动核心 UI。 | 高级能力仍需本机工具/配置；Quickstart 已说明。 | `rsync --exclude .git` 到 `/tmp` 后 `./run.sh`，`/api/health` ok。 |

## 下一批优先实现

1. **Standalone WeChat bridge runner**：不启动第二 poller，只消费当前 LingTai MCP 桥接出的消息，负责 ACK、状态同步、回传。
2. **统一 Task Router**：普通任务 / 真实 avatar / daemon / Claude / Codex / mailbox 派发与结果汇总。
3. **Secret Vault health 扫描**：启动时发现明文 key 风险并给迁移提示。
4. **累计预算/成本面板**：provider/任务维度 cost cap、长跑告警、与确认队列联动。

## 机器可读状态

本矩阵也暴露为本地 API：

```bash
curl http://127.0.0.1:8765/api/architecture/status
```

前端入口：打开本地 UI 后点击 **“📋 架构验收表”**。
