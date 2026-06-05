/* 圆酱专属轻量版灵台 v0.6 — 前端逻辑（纯原生 JS，无依赖） */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let STATE = null;
let CATALOG = null;

// ---------- API ----------
async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opt);
  const data = await res.json();
  if (data.state) STATE = data.state;
  return data;
}

async function refresh() {
  const res = await fetch("/api/state");
  STATE = await res.json();
  render();
}

async function loadCatalog() {
  const res = await fetch("/api/catalog");
  CATALOG = await res.json();
}

// ---------- 工具 ----------
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
}
function statusTag(status) {
  const map = {
    "待命": "idle", "正在干": "busy", "卡住": "stuck", "等确认": "waiting",
    "已暂停": "paused", "完成": "done", "已拒绝": "denied",
    "排队中": "busy", "执行中": "busy", "待确认": "waiting", "已确认": "done",
    "待派": "waiting",
  };
  return `<span class="tag ${map[status] || "idle"}">${esc(status)}</span>`;
}

// ---------- Modal ----------
function openModal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }

// ---------- 渲染 ----------
function render() {
  if (!STATE) return;
  const s = STATE.stats || {};
  $("#stat-agents").textContent = `灵 ${s.agent_count || 0} / ${s.max_agents || 5}`;
  $("#stat-approvals").textContent = `待确认 ${s.pending_approvals || 0}`;

  renderAgents();
  renderTasks();
  renderWechat();
  renderApprovals();
  renderProviders();
  renderCCLevels();
  renderCCRuns();
  renderPressure();
  renderLog();
}

function renderAgents() {
  const el = $("#agents");
  if (!STATE.agents.length) {
    el.innerHTML = `<div class="empty">还没有灵。点上面「🌱 新建一个灵」开始。</div>`;
    return;
  }
  el.innerHTML = STATE.agents.map(a => {
    const high = (a.context_pressure || 0) >= 70;
    return `
    <div class="agent">
      <div class="agent-head">
        <span class="agent-name">${esc(a.name)}</span>
        ${statusTag(a.status)}
      </div>
      <div class="agent-meta">
        <span class="tag role">${esc(a.role)}</span>
        ${a.model ? "· 模型 " + esc(a.model) : "· 未配模型"}
        · CC 等级 ${a.cc_level}
      </div>
      <div class="bar ${high ? "high" : ""}"><span style="width:${a.context_pressure || 0}%"></span></div>
      <div class="agent-meta">context 压力 ${a.context_pressure || 0}%</div>
      <div class="row-actions">
        <button class="btn small" onclick="quickAssign('${a.id}')">派任务</button>
        ${a.status === "已暂停"
          ? `<button class="btn small ok" onclick="agentAction('${a.id}','resume')">恢复</button>`
          : `<button class="btn small" onclick="agentAction('${a.id}','pause')">暂停</button>`}
        <button class="btn small danger" onclick="agentAction('${a.id}','delete')">删除</button>
      </div>
    </div>`;
  }).join("");
}

function renderTasks() {
  const el = $("#tasks");
  if (!STATE.tasks.length) { el.innerHTML = `<div class="empty">暂无任务。</div>`; return; }
  el.innerHTML = STATE.tasks.map(t => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(t.description)}</span>
        ${statusTag(t.status)}
      </div>
      <div class="row-sub">
        承接：${esc(t.agent_name)} · 来源：${t.source === "wechat" ? "💬 微信" : "🖥️ 界面"}
        ${t.risk === "sensitive" ? "· ⚠️ 敏感" : ""}
        ${t.result ? "<br>结果：" + esc(t.result) : ""}
      </div>
    </div>`).join("");
}

function renderWechat() {
  const el = $("#wechat");
  const inbox = STATE.wechat_inbox || [];
  const outbox = STATE.wechat_outbox || [];
  const bridge = STATE.wechat_bridge || {};
  const bridgeBanner = `<div class="preview">桥接状态：${esc(bridge.status || "unknown")} · ${esc(bridge.note || "")}</div>`;
  const inboxHtml = inbox.length ? inbox.map(w => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">💬 ${esc(w.text)}</span>
        ${statusTag(w.status)}
      </div>
      <div class="row-sub">
        ${esc(w.ack)}<br>
        阶段：${(w.stages || []).map(esc).join(" → ")}<br>
        来源：${esc(w.source || "local")}${w.message_id ? " · 微信消息 " + esc(w.message_id) : ""}<br>
        承接：${esc(w.assignee)}${w.result ? "<br>回复/桥接结果：" + esc(w.result) : ""}
      </div>
    </div>`).join("") : `<div class="empty">微信队列为空。真实运行时，圆酱微信消息会由当前 LingTai WeChat MCP 桥接写入这里。</div>`;
  const outboxHtml = outbox.length ? `<h4>待原路回复 / 已回复</h4>` + outbox.map(o => `
    <div class="row">
      <div class="row-top"><span class="row-title">↩ ${esc(o.reply_text || "")}</span>${statusTag(o.status || "ready_for_bridge")}</div>
      <div class="row-sub">outbox：${esc(o.id)} · inbound：${esc(o.inbound_id || "")} · transport：${esc(o.transport || "")}</div>
    </div>`).join("") : "";
  el.innerHTML = bridgeBanner + inboxHtml + outboxHtml;
}

function renderApprovals() {
  const el = $("#approvals");
  if (!STATE.approvals.length) { el.innerHTML = `<div class="empty">确认队列为空。敏感动作会出现在这里。</div>`; return; }
  el.innerHTML = STATE.approvals.map(a => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(a.title)}</span>
        ${statusTag(a.status)}
      </div>
      <div class="row-sub">动作类型：<code>${esc(a.action)}</code></div>
      <div class="preview">${esc(a.preview)}</div>
      ${a.status === "待确认" ? `
      <div class="row-actions">
        <button class="btn ok small" onclick="approval('${a.id}','approve')">确认/执行</button>
        <button class="btn danger small" onclick="approval('${a.id}','deny')">拒绝</button>
      </div>` : ""}
    </div>`).join("");
}

function renderProviders() {
  const el = $("#providers");
  if (!STATE.providers.length) { el.innerHTML = `<div class="empty">还没有配置任何供应商。</div>`; return; }
  el.innerHTML = STATE.providers.map(p => {
    const hasKey = p.in_keychain || p.configured;
    return `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(p.name)}</span>
        ${hasKey ? `<span class="tag done">🔐 Keychain${p.key_last4 ? " ····" + esc(p.key_last4) : ""}</span>` : `<span class="tag waiting">未配置 key</span>`}
      </div>
      <div class="row-sub">
        base_url：${esc(p.base_url || "(未设置)")}<br>
        模型：${esc(p.model || "(未设置)")} ${p.key_label ? "· 标签 " + esc(p.key_label) : ""}
      </div>
      <div class="cap-tags">${(p.tags || []).map(t => `<span class="ct">${esc(t)}</span>`).join("")}</div>
    </div>`;
  }).join("");
}

function renderCCLevels() {
  const el = $("#cc-levels");
  if (!CATALOG) return;
  el.innerHTML = CATALOG.cc_levels.map(l => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">等级 ${l.level} · ${esc(l.label)}</span>
        ${l.needs_approval ? `<span class="tag waiting">需确认</span>` : `<span class="tag done">可直接</span>`}
      </div>
    </div>`).join("");
}

function renderCCRuns() {
  const el = $("#cc-runs");
  if (!el) return;
  const runs = STATE.cc_runs || [];
  if (!runs.length) { el.innerHTML = `<div class="empty">暂无 Claude Code 运行记录。</div>`; return; }
  el.innerHTML = runs.map(r => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(r.description || r.id)}</span>
        ${statusTag(r.status || "未知")}
      </div>
      <div class="row-sub">run：${esc(r.id)} · 等级：${esc(r.label || r.level)}${r.duration_ms ? " · " + esc(r.duration_ms) + "ms" : ""}${r.report_path ? "<br>报告：" + esc(r.report_path) : ""}</div>
      ${r.output_preview ? `<div class="preview">${esc(r.output_preview)}</div>` : ""}
    </div>`).join("");
}

function renderPressure() {
  const el = $("#pressure");
  if (!STATE.agents.length) { el.innerHTML = `<div class="empty">暂无灵。</div>`; return; }
  el.innerHTML = STATE.agents.map(a => {
    const high = (a.context_pressure || 0) >= 70;
    return `
    <div class="pressure-item">
      <div class="pl-top"><span>${esc(a.name)}</span><span>${a.context_pressure || 0}%${high ? " ⚠️ 建议收束" : ""}</span></div>
      <div class="bar ${high ? "high" : ""}"><span style="width:${a.context_pressure || 0}%"></span></div>
    </div>`;
  }).join("");
}

function renderLog() {
  const el = $("#log");
  if (!STATE.log.length) { el.innerHTML = `<div class="empty">暂无事件。</div>`; return; }
  el.innerHTML = STATE.log.map(l => `
    <div class="log-item"><span class="lt">${esc((l.ts || "").replace("T", " ").slice(5, 19))}</span>${esc(l.message)}</div>`).join("");
}

// ---------- 操作 ----------
async function agentAction(id, action) {
  if (action === "delete") {
    if (!confirm("删除灵需要进确认队列（敏感动作）。继续？")) return;
    const r = await api("/api/agent/delete", { agent_id: id });
    if (r.ok) toast("已加入确认队列：删除灵");
  } else {
    const r = await api(`/api/agent/${action}`, { agent_id: id });
    if (r.ok) toast(action === "pause" ? "已暂停" : "已恢复");
  }
  render();
}

async function approval(id, decision) {
  const r = await api(`/api/approval/${decision}`, { approval_id: id });
  if (r.ok) toast(decision === "approve" ? "已确认/执行" : "已拒绝");
  else toast(r.error || "操作失败");
  render();
}

function quickAssign(agentId) {
  openTaskModal(agentId);
}

// ---------- 各大按钮的 Modal ----------
function openNewAgentModal() {
  const provOptions = CATALOG.providers.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  const ccOptions = CATALOG.cc_levels.map(l => `<option value="${l.level}">${l.level} · ${esc(l.label)}</option>`).join("");
  const full = STATE.agents.length >= CATALOG.max_agents;
  openModal("🌱 新建一个灵", `
    ${full ? `<div class="preview">已达上限 ${CATALOG.max_agents} 个灵，请先删除一个。</div>` : ""}
    <label>给它起个名字</label>
    <input id="na-name" placeholder="例如：营养审稿灵" />
    <label>它是哪种？</label>
    <select id="na-role">
      <option value="长期助手">长期助手（resident）</option>
      <option value="临时分析">临时分析（daemon）</option>
      <option value="代码苦力">代码苦力（Claude Code）</option>
    </select>
    <label>用哪个模型/供应商</label>
    <select id="na-provider">${provOptions}</select>
    <label>模型名（可选）</label>
    <input id="na-model" placeholder="例如：deepseek-chat" />
    <label>Claude Code 权限等级</label>
    <select id="na-cc">${ccOptions}</select>
    <button class="btn primary" ${full ? "disabled" : ""} onclick="submitNewAgent()">创建</button>
  `);
}
async function submitNewAgent() {
  const r = await api("/api/agent/create", {
    name: $("#na-name").value,
    role: $("#na-role").value,
    provider_id: $("#na-provider").value,
    model: $("#na-model").value,
    cc_level: $("#na-cc").value,
  });
  if (r.ok) { toast("已新建灵 🌱"); closeModal(); render(); }
  else toast(r.error || "创建失败");
}

function openTaskModal(presetAgentId) {
  if (!STATE.agents.length) { toast("请先新建一个灵"); return openNewAgentModal(); }
  const opts = STATE.agents.map(a =>
    `<option value="${a.id}" ${a.id === presetAgentId ? "selected" : ""}>${esc(a.name)}（${esc(a.status)}）</option>`).join("");
  openModal("📨 本地记录任务", `
    <label>派给哪个灵</label>
    <select id="tk-agent">${opts}</select>
    <label>任务内容（一句话）</label>
    <textarea id="tk-desc" placeholder="例如：读这个仓库的 README 并总结要点"></textarea>
    <label>风险等级</label>
    <select id="tk-risk">
      <option value="low">普通（只读/本地记录，自动完成）</option>
      <option value="sensitive">敏感（外发/改码 — 进确认队列）</option>
    </select>
    <button class="btn primary" onclick="submitTask()">派活</button>
  `);
}
async function submitTask() {
  const r = await api("/api/task/assign", {
    agent_id: $("#tk-agent").value,
    description: $("#tk-desc").value,
    risk: $("#tk-risk").value,
    source: "ui",
    action_type: "wechat_send",
  });
  if (r.ok) {
    toast(r.result && r.result.status === "等确认" ? "敏感任务已进确认队列" : "已派活并完成本地记录");
    closeModal(); render();
  } else toast(r.error || "派活失败");
}

function openModelsModal() {
  const kc = CATALOG && CATALOG.keychain_available;
  const opts = CATALOG.providers
    .map(p => `<option value="${p.id}" data-url="${esc(p.default_base_url)}" data-model="${esc(p.default_model || "")}">${esc(p.name)}</option>`)
    .join("");
  const kcBanner = kc
    ? `<div class="preview">🔐 真实能力：API key 会被存进 <b>Mac 系统 Keychain</b>，不会写入 state.json / 日志 / 界面。后端只保留「已配置 + 后四位」用于展示。</div>`
    : `<div class="preview">⚠️ 本机没有 macOS <code>security</code> 命令，Keychain 不可用。为防明文泄露，<b>无法保存 key</b>；你仍可保存 base_url / 模型名（不含 key）。</div>`;
  openModal("🧠 模型 / API 中心", `
    ${kcBanner}
    <label>供应商</label>
    <select id="pv-id" onchange="onProviderPick()">${opts}</select>
    <label>base_url（可编辑）</label>
    <input id="pv-url" placeholder="https://..." />
    <label>模型名（可编辑）</label>
    <input id="pv-model" placeholder="例如：gpt-4o-mini / deepseek-chat / glm-4-flash" />
    <label>API Key（明文只进 Keychain，不回显、不入库）</label>
    <input id="pv-key" type="password" placeholder="${kc ? "粘贴 key（存入系统 Keychain）" : "Keychain 不可用，无法保存 key"}" ${kc ? "" : "disabled"} />
    <label>Key 标签（可选，便于你识别）</label>
    <input id="pv-label" placeholder="例如：圆酱-个人额度" />
    <div class="row-actions">
      <button class="btn primary" onclick="submitProvider()">保存配置${kc ? "（key 存 Keychain）" : ""}</button>
      <button class="btn small" onclick="checkProviderKey()">检查 Keychain</button>
      <button class="btn small danger" onclick="deleteProviderKey()">删除 Keychain key</button>
    </div>

    <hr class="soft" />
    <div class="preview">💸 <b>真实模型调用</b>：下面这一步会通过你保存的 key 向供应商发起 <b>真实网络请求，可能产生费用</b>。其余高危动作中，rollback 已接入本仓库 git Time Machine（确认后真实 reset）；外发 / commit / PR / merge 仍为预览，需下一阶段接入。</div>
    <label>测试提示词（可选）</label>
    <input id="pv-prompt" placeholder="例如：用一句话确认你能正常回复" />
    <label class="checkrow"><input type="checkbox" id="pv-confirm-cost" /> 我已知道这是真实调用、可能产生费用</label>
    <button class="btn warn" onclick="submitModelTest()">▶ 运行真实模型测试（可能花钱）</button>
    <div id="pv-test-result"></div>
  `);
  onProviderPick();
}
function onProviderPick() {
  const sel = $("#pv-id");
  const opt = sel.options[sel.selectedIndex];
  const url = opt.getAttribute("data-url");
  const model = opt.getAttribute("data-model");
  // 若已保存过该供应商，优先回填已存的 base_url / model
  const saved = (STATE.providers || []).find(p => p.provider_id === sel.value);
  $("#pv-url").value = (saved && saved.base_url) || url || "";
  $("#pv-model").value = (saved && saved.model) || model || "";
}
async function submitProvider() {
  const r = await api("/api/provider/save", {
    provider_id: $("#pv-id").value,
    base_url: $("#pv-url").value,
    model: $("#pv-model").value,
    api_key: $("#pv-key").value,   // 明文仅用于写 Keychain，后端不入库
    key_label: $("#pv-label").value,
  });
  if (r.ok) {
    $("#pv-key").value = "";
    toast(r.result && r.result.in_keychain ? "已保存，key 已进 Keychain 🔐" : "已保存配置（无 key）");
    render();
  } else toast(r.error || "保存失败");
}
async function checkProviderKey() {
  const r = await api("/api/provider/check_key", { provider_id: $("#pv-id").value });
  if (r.ok) {
    if (!r.result.keychain_available) toast("Keychain 不可用：" + (r.result.note || ""));
    else toast(r.result.in_keychain ? "Keychain 里有这个 key ✅" : "Keychain 里没有这个 key");
    render();
  } else toast(r.error || "检查失败");
}
async function deleteProviderKey() {
  if (!confirm("从 Mac Keychain 删除该供应商的 key？")) return;
  const r = await api("/api/provider/delete_key", { provider_id: $("#pv-id").value });
  if (r.ok) { toast("已从 Keychain 删除 key"); render(); }
  else toast(r.error || "删除失败");
}
async function submitModelTest() {
  if (!$("#pv-confirm-cost").checked) return toast("请先勾选「我已知道这是真实调用、可能产生费用」");
  const box = $("#pv-test-result");
  if (box) box.innerHTML = `<div class="preview">⏳ 正在发起真实调用…</div>`;
  const r = await api("/api/model/test", {
    provider_id: $("#pv-id").value,
    base_url: $("#pv-url").value,
    model: $("#pv-model").value,
    prompt: $("#pv-prompt").value,
    confirm_cost: true,
  });
  if (!box) return;
  if (r.ok) {
    const res = r.result || {};
    box.innerHTML = `<div class="preview">✅ 真实调用成功 · 模型 ${esc(res.model || "")} · ${esc(String(res.latency_ms || "?"))}ms
${res.usage ? "· tokens " + esc(JSON.stringify(res.usage)) : ""}</div>
      <div class="preview" style="white-space:pre-wrap;">${esc(res.reply || "(无文本回复)")}</div>`;
    toast("真实模型调用成功 ✅");
    render();
  } else {
    box.innerHTML = `<div class="preview">❌ 调用失败：${esc(r.error || "未知错误")}</div>`;
    toast("真实调用失败");
  }
}

function openWechatModal() {
  openModal("💬 微信入口任务 / 桥接测试", `
    <div class="preview">v0.6 已接入真实微信桥接端点：实际运行时由当前 LingTai WeChat MCP 把圆酱微信消息写入本服务，再原路回复；这里仍可手动提交一条本地测试消息。</div>
    <label>本地测试一条微信任务</label>
    <textarea id="wx-modal-input" placeholder="例如：让代码苦力改个 README，但不要提交"></textarea>
    <button class="btn primary" onclick="submitWechatModal()">写入微信桥接队列</button>
  `);
}
async function submitWechatModal() {
  const text = $("#wx-modal-input").value;
  const r = await api("/api/wechat/submit", { text });
  if (r.ok) { toast("微信桥接任务已入队"); closeModal(); render(); }
  else toast(r.error || "提交失败");
}

function openCCModal() {
  const opts = CATALOG.cc_levels.map(l =>
    `<option value="${l.level}">${l.level} · ${esc(l.label)}${l.needs_approval ? "（需确认）" : "（可直接）"}</option>`).join("");
  openModal("🛠️ Claude Code 苦力", `
    <div class="preview">L1 会真实调用本机 Claude Code 只读分析（可能产生费用，需勾选确认）；仅允许 Read/Grep/Glob，不允许改文件。L2+ 改码/commit/PR/merge 仍只进确认队列，尚未接入真实执行器。</div>
    <label>权限等级</label>
    <select id="cc-level">${opts}</select>
    <label>代码任务描述</label>
    <textarea id="cc-desc" placeholder="例如：只读分析仓库结构 / 找 README 中还像 AI 的段落"></textarea>
    <label class="checkline"><input type="checkbox" id="cc-confirm-cost" /> 我确认 L1 只读分析会真实调用 Claude Code，可能产生费用；不把凭证写进任务描述。</label>
    <button class="btn primary" onclick="submitCC()">派代码苦力</button>
  `);
}
async function submitCC() {
  const r = await api("/api/cc/request", {
    level: $("#cc-level").value,
    description: $("#cc-desc").value,
    confirm_cost: $("#cc-confirm-cost")?.checked || false,
  });
  if (r.ok) {
    if (r.result.queued_approval) toast("已进确认队列（敏感代码动作）");
    else toast(r.result.status === "完成" ? "Claude Code 只读分析已完成" : "Claude Code 请求已处理");
    closeModal(); render();
  } else toast(r.error || "失败");
}

function openApprovalsModal() {
  // 直接滚动到确认队列卡
  $$(".card.accent")[0]?.scrollIntoView({ behavior: "smooth" });
  toast("确认队列在下方高亮卡片中");
}

async function openShougongModal() {
  const r = await api("/api/shougong", {});
  if (!r.ok) return toast("生成失败");
  const md = r.result.markdown;
  openModal("📋 收功单 / Shougong", `
    <div class="preview">已保存到：${esc(r.result.path)}</div>
    <textarea style="min-height:340px;font-family:ui-monospace,monospace;font-size:12px;">${esc(md)}</textarea>
    <button class="btn" onclick="copyShougong(this)">复制 Markdown</button>
  `);
  render();
}
function copyShougong(btn) {
  const ta = btn.parentElement.querySelector("textarea");
  ta.select();
  navigator.clipboard?.writeText(ta.value).then(() => toast("已复制")).catch(() => toast("请手动复制"));
}

async function openRollbackModal() {
  const res = await fetch("/api/rollback/preview");
  const data = await res.json();
  const snaps = (data.snapshots || []).map(s => `
    <div class="row">
      <div class="row-top"><span class="row-title">${esc(s.label)}</span><span class="tag ${s.kind === 'safety' ? 'warn' : 'idle'}">${esc(s.kind || 'snapshot')} · ${esc(s.id)}</span></div>
      <div class="row-sub">创建：${esc((s.created_at || "").slice(0, 19).replace("T", " "))} · commit ${esc(s.short_commit || '')}</div>
      <div class="preview">${esc(s.diff_preview || '')}</div>
      <div class="row-actions">
        <button class="btn small danger" onclick="requestRollback('${esc(s.id)}')">回退到这里（先进入确认队列）</button>
      </div>
    </div>`).join("") || `<div class="empty">还没有快照。先点“创建当前安全快照”。</div>`;
  openModal("⏪ 时间机器 / Rollback（真实）", `
    <div class="preview">${esc(data.note)}</div>
    <div class="preview">当前 HEAD：${esc(data.current_head || 'unknown')}；工作区：${data.dirty ? '有未提交改动' : '干净'}<br><pre>${esc(data.status_short || '')}</pre></div>
    <div class="row-actions">
      <input id="snapshotLabel" placeholder="快照名称，例如：改 UI 前安全点" value="手动安全快照" />
      <button class="btn" onclick="createSnapshot()">创建当前安全快照（真实 git ref）</button>
    </div>
    ${snaps}
  `);
}
async function createSnapshot() {
  const label = document.getElementById('snapshotLabel')?.value || '手动安全快照';
  const r = await api("/api/rollback/snapshot", { label });
  if (r.ok) { toast("已创建真实 git 快照"); openRollbackModal(); render(); }
  else toast(r.error || "创建失败");
}
async function requestRollback(id) {
  const r = await api("/api/rollback/request", { snapshot_id: id });
  if (r.ok) { toast("已进确认队列：批准后会真实 git reset --hard"); closeModal(); render(); }
  else toast(r.error || "失败");
}


async function loadDemoState() {
  if (!confirm("加载示例状态会覆盖当前原型数据，继续？")) return;
  const r = await api("/api/demo/load", {});
  if (r.ok) { await refresh(); toast("已加载示例状态 ✨"); }
  else toast(r.error || "加载示例失败");
}

async function openHealthModal() {
  const res = await fetch("/api/health");
  const h = await res.json();
  const rows = Object.entries(h.checks || {}).map(([k,v]) =>
    `<div class="row"><div class="row-top"><span class="row-title">${esc(k)}</span><span class="tag ${v ? "done" : "danger"}">${v ? "OK" : "FAIL"}</span></div></div>`).join("");
  openModal("🩺 健康检查 / Self-check", `
    <div class="preview">版本：${esc(h.version)} · 地址：${esc(h.host)}:${esc(String(h.port))} · 总体：${h.ok ? "OK" : "FAIL"}</div>
    ${rows}
    <div class="preview">边界：${esc((h.boundaries || []).join(" / "))}</div>
  `);
}

function openDocsModal() {
  openModal("📖 怎么看这个原型", `
    <div class="preview">这是圆酱专属轻量版灵台 <b>v0.6 — 微信桥接入口真实接入里程碑</b>。真实能力逐步接入：<b>模型 API 已真实可用</b>（key 进 Mac Keychain，可发真实请求）；<b>Rollback / Time Machine 已真实接入本仓库 git 快照与确认后 reset</b>；<b>微信入口已通过现有 LingTai WeChat MCP 做真实桥接</b>；L1 Claude Code 只读分析已接入；commit / PR / merge 仍需下一阶段接入。本地 Python 服务只是其中一个组件，后续会加 GUI / Mac 应用外壳与真实 LingTai / Claude Code / 微信集成。</div>
    <ol>
      <li>点「模型 / API 中心」，保存某个供应商的 key（会进系统 Keychain）。</li>
      <li>勾选「我已知道这是真实调用、可能产生费用」后点「▶ 运行真实模型测试」。</li>
      <li>点「新建一个灵」创建子灵；用「本地记录任务」「微信入口任务」体验编排。</li>
      <li>敏感动作进入「确认队列」，先预览；rollback 和 Claude Code L1 只读分析已是真实链路，改码/PR/merge 仍未接入。</li>
      <li>点「一键收功」生成可返回的阶段小结。</li>
    </ol>
    <div class="preview">Mac 双击启动：运行目录里的「启动圆酱灵台.command」。</div>
  `);
}

// ---------- 绑定 ----------
const ACTIONS = {
  "new-agent": openNewAgentModal,
  "assign-task": () => openTaskModal(),
  "wechat": openWechatModal,
  "models": openModelsModal,
  "cc": openCCModal,
  "approvals": openApprovalsModal,
  "shougong": openShougongModal,
  "rollback": openRollbackModal,
  "load-demo": loadDemoState,
  "health": openHealthModal,
  "open-docs": openDocsModal,
};

function bind() {
  $$("[data-act]").forEach(b => b.addEventListener("click", () => {
    const fn = ACTIONS[b.dataset.act];
    if (fn) fn();
  }));
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  $("#wx-send").addEventListener("click", async () => {
    const text = $("#wx-input").value;
    if (!text.trim()) return toast("请输入微信任务");
    const r = await api("/api/wechat/submit", { text });
    if (r.ok) { $("#wx-input").value = ""; toast("微信桥接任务已入队"); render(); }
    else toast(r.error || "失败");
  });
  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("重置原型所有数据？")) return;
    await api("/api/reset", {});
    await refresh();
    toast("已重置");
  });
}

// ---------- 启动 ----------
(async function init() {
  await loadCatalog();
  await refresh();
  bind();
  // 轻量轮询，模拟实时状态
  setInterval(refresh, 5000);
})();

// 暴露给内联 onclick
window.agentAction = agentAction;
window.approval = approval;
window.quickAssign = quickAssign;
window.submitNewAgent = submitNewAgent;
window.submitTask = submitTask;
window.submitProvider = submitProvider;
window.checkProviderKey = checkProviderKey;
window.deleteProviderKey = deleteProviderKey;
window.submitModelTest = submitModelTest;
window.onProviderPick = onProviderPick;
window.submitWechatModal = submitWechatModal;
window.submitCC = submitCC;
window.copyShougong = copyShougong;
window.requestRollback = requestRollback;
