# LingTai Simple v0.3 Implementation Report

## 结论

v0.3 从 v0.2 的纯本地 mock，升级为**第一批真实能力接入**：Mac Keychain 密钥保险柜 + OpenAI-compatible 真实模型调用。

同时按圆酱纠正，主界面不再把微信、Claude Code、rollback 等未接入能力当成已完成大按钮；这些能力被灰显/标注为下一阶段，不算完成功能。

## 已实现

- `server.py`
  - 本地 HTTP 服务仍默认绑定 `127.0.0.1`。
  - provider 配置保存：base_url/model 写入本地状态；API key 写入 Mac Keychain。
  - Keychain 实现改为 macOS `Security.framework` + Python `ctypes`，避免通过 `security -w <key>` 把 key 暴露在子进程 argv。
  - `/api/model/test` 发起真实 OpenAI-compatible `/chat/completions` 请求；需要 `confirm_cost=true`。
  - 模型调用有 timeout 与 max_tokens 上限。
  - 错误与日志走脱敏。

- `static/index.html` / `static/app.js` / `static/styles.css`
  - 模型/API中心提供真实 Keychain 保存、检查、删除、真实模型测试。
  - 微信 bot、Claude Code、rollback 灰显或标注“下一阶段真实接入”。
  - 页面文案明确：只展示真实接入能力；未接入不算完成。

- `scripts/self_check.py`
  - 启动本地服务自检。
  - 用假 key 验证 Keychain 安全路径；即使系统拒绝写入，也确认不会明文落盘。
  - 验证未勾选费用确认时 `/api/model/test` 拒绝调用。
  - 不触发真实外部模型 API。

- `README.md`
  - 重写 v0.3 边界：已接入 / 未接入 分清。
  - 不再用“全部 mock 但安全”当卖点。

## 未实现 / 不算完成

- 真实微信 bot 指令入口。
- 真实 Claude Code worker。
- 真实 commit / push / PR / merge。
- 真实 rollback / Time Machine。
- 真正的 Mac app 外壳。
- 与 LingTai runtime/mailbox/skills/memory 的完整接入。

## 本地验证

已运行：

```bash
python3 -m py_compile server.py scripts/self_check.py scripts/load_demo.py
python3 scripts/self_check.py
```

结果：

```text
OK LingTai Simple v0.3 self-check passed
```

当前机器为非交互 agent session，Keychain 写入可能被系统拒绝；这是安全失败路径。自检确认没有退化为明文存储。

## 安全说明

- 明文 API key 不进入 `state.json`。
- Keychain 写入不通过 shell 参数传 key。
- `self_check.py` 使用假 key，且检查假 key 未落盘。
- 真实模型调用必须由 UI 显式触发，并勾选费用确认。
- 供应商端点：OpenAI、DeepSeek、GLM 使用常见 OpenAI-compatible base_url；MiMo、MiniMax 不硬编未核验 endpoint，要求用户填写兼容端点。

## 下一步建议

圆酱最新明确要求：轻量版灵台必须像当前灵台一样通过微信 bot 交互。因此下一阶段应优先：

1. 接真实 WeChat addon / mailbox：微信发指令 → 本地服务收到 → 入任务队列。
2. 建确认协议：高危动作通过微信二次确认。
3. 接真实 Claude Code worker：受控 worktree + 权限等级。
4. 再做 Mac app 包装。
