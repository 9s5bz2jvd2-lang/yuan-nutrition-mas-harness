/* 圆酱专属轻量版灵台 v0.20 — 前端逻辑（纯原生 JS，无依赖） */

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
function money(v) {
  const n = Number(v || 0);
  return "$" + n.toFixed(n >= 1 ? 2 : 6);
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
    "待派": "waiting", "已派发": "busy",
    "queued_to_lingtai_outbox": "busy", "reply_received": "done",
    "sleep_signal_written": "paused", "suspend_signal_written": "paused", "interrupt_signal_written": "waiting", "clear_signal_written": "waiting",
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
  renderLingTaiRuntime();
  renderLingTaiMemory();
  renderApprovals();
  renderProviders();
  renderCostPanel();
  renderCCLevels();
  renderCCRuns();
  renderOrchestrations();
  renderInsights();
  renderSoulFlows();
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
        ${a.lingtai_address ? " · 真实地址 " + esc(a.lingtai_address) : ""}
      </div>
      <div class="bar ${high ? "high" : ""}"><span style="width:${a.context_pressure || 0}%"></span></div>
      <div class="agent-meta">context 压力 ${a.context_pressure || 0}%</div>
      <div class="row-actions">
        <button class="btn small" onclick="quickAssign('${a.id}')">派任务</button>
        <button class="btn small ok" onclick="openLingTaiRuntimeModal('', '${a.lingtai_address || ''}')">真实派发</button>
        ${a.status === "已暂停"
          ? `<button class="btn small ok" onclick="agentAction('${a.id}','resume')">恢复</button>`
          : `<button class="btn small" onclick="agentAction('${a.id}','pause')">暂停</button>`}
        <button class="btn small danger" onclick="agentAction('${a.id}','delete')">${a.lingtai_address ? "退休/解绑" : "删除"}</button>
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
      <div class="row-actions"><button class="btn small ok" onclick="openLingTaiRuntimeModal('${t.id}', '')">派到真实 LingTai agent</button></div>
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

function renderLingTaiRuntime() {
  const el = $("#lingtai-runtime");
  if (!el) return;
  const rt = STATE.lingtai_runtime || {};
  const rows = STATE.lingtai_dispatches || [];
  const replies = STATE.lingtai_mail_results || [];
  const life = STATE.lingtai_lifecycle_events || [];
  const avatars = STATE.lingtai_avatar_events || [];
  const banner = `<div class="preview">运行态：${esc(rt.status || "unknown")} · sender=${esc(rt.sender || "human")} · reply_inbox=${esc(rt.reply_inbox || "mimo-2-5-pro")}<br>网络：${esc(rt.network_dir || "未找到")}<br>${esc(rt.note || "")}</div>
    <div class="row-actions">
      <button class="btn small ok" onclick="collectLingTaiReplies()">回收真实 agent 回复</button>
      <button class="btn small warn" onclick="openLingTaiLifecycleModal()">生命周期动作</button>
      <button class="btn small ok" onclick="openLingTaiAvatarModal()">创建真实 avatar</button>
      <button class="btn small" onclick="openLingTaiBindModal()">绑定既有 agent</button>
      <button class="btn small warn" onclick="openLingTaiRetireModal()">退休/解绑 avatar</button>
      <button class="btn small ok" onclick="refreshLingTaiMemory()">刷新记忆/技能索引</button>
    </div>`;
  const dispatches = rows.length ? `<h4>真实派发记录</h4>` + rows.map(d => `
    <div class="row">
      <div class="row-top"><span class="row-title">📮 ${esc(d.subject || d.mailbox_id)}</span>${statusTag(d.status || "queued_to_lingtai_outbox")}</div>
      <div class="row-sub">${esc(d.from)} → ${esc(d.to)} · mailbox ${esc(d.mailbox_id)}${d.last_reply_at ? " · reply " + esc(d.last_reply_at) : ""}<br>${esc(d.outbox_path || "")}</div>
    </div>`).join("") : `<div class="empty">还没有真实 LingTai 邮箱派发记录。</div>`;
  const replyHtml = replies.length ? `<h4>已回收真实回复</h4>` + replies.map(r => `
    <div class="row">
      <div class="row-top"><span class="row-title">↩ ${esc(r.subject || r.mailbox_id)}</span>${statusTag("reply_received")}</div>
      <div class="row-sub">from ${esc(r.from)} · ${esc(r.received_at || "")} · dispatch ${esc(r.dispatch_id || "")}</div>
      <div class="preview">${esc(r.message_preview || "")}</div>
    </div>`).join("") : "";
  const lifeHtml = life.length ? `<h4>生命周期动作记录</h4>` + life.map(e => `
    <div class="row">
      <div class="row-top"><span class="row-title">⚙ ${esc(e.action)} ${esc(e.address)}</span>${statusTag(e.status || "done")}</div>
      <div class="row-sub">${esc(e.created_at || "")}</div>
    </div>`).join("") : "";
  const avatarHtml = avatars.length ? `<h4>真实 avatar 管理记录</h4>` + avatars.map(e => `
    <div class="row">
      <div class="row-top"><span class="row-title">🧬 ${esc(e.event || "spawn")} · ${esc(e.name || e.address)}</span>${statusTag(e.boot_status || e.status || "started")}</div>
      <div class="row-sub">address ${esc(e.address || "")} · template ${esc(e.template_address || "")} · pid ${esc(String(e.pid || ""))} · ${esc(e.created_at || "")}<br>${esc(e.working_dir || "")}${e.note ? "<br>备注：" + esc(e.note) : ""}</div>
    </div>`).join("") : "";
  el.innerHTML = banner + dispatches + replyHtml + lifeHtml + avatarHtml;
}


function renderLingTaiMemory() {
  const el = $("#lingtai-memory");
  if (!el) return;
  const scans = STATE.lingtai_memory_scans || [];
  const latest = scans[0];
  const c = latest?.counts || {};
  const banner = `<div class="preview">只读索引真实 LingTai durable stores：pad / knowledge / custom skills / shared skills / molt summaries。不会读取 .secrets、mailbox、logs；打开文件也限制在这些目录内。</div>
    <div class="row-actions">
      <button class="btn small ok" onclick="refreshLingTaiMemory()">刷新真实索引</button>
      <button class="btn small" onclick="openLingTaiMemoryModal()">查看索引</button>
    </div>`;
  const summary = latest ? `<div class="row">
      <div class="row-top"><span class="row-title">最近扫描：${esc(latest.scanned_at || "")}</span>${statusTag("read_only")}</div>
      <div class="row-sub">pad ${c.pad || 0} · knowledge ${c.knowledge || 0} · skills ${c.skills || 0} · summaries ${c.summaries || 0}<br>${esc(latest.agent_dir || "")}</div>
    </div>` : `<div class="empty">尚未刷新真实记忆/技能索引。</div>`;
  el.innerHTML = banner + summary;
}

function memoryRows(items, label) {
  if (!items || !items.length) return `<h4>${esc(label)}</h4><div class="empty">无</div>`;
  return `<h4>${esc(label)}</h4>` + items.map(it => `
    <div class="row">
      <div class="row-top"><span class="row-title">${esc(it.name || it.path)}</span>${it.source ? statusTag(it.source) : ""}</div>
      <div class="row-sub">${esc(it.description || "")}<br>${esc(it.path || "")} · ${esc(String(it.size || 0))} bytes · ${esc(it.mtime || "")}</div>
      <div class="row-actions"><button class="btn small" onclick="readLingTaiMemory('${esc(String(it.path || "").replace(/'/g, "&#39;"))}')">只读打开</button></div>
    </div>`).join("");
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

function keySourceLabel(p) {
  const source = p.key_source || (p.in_keychain ? "keychain" : (p.env_slot_present ? "env" : (p.secret_file_present ? "secret_file" : "")));
  const tail = p.key_last4 ? " ····" + esc(p.key_last4) : "";
  if (source === "keychain") return `<span class="tag done">🔐 Keychain${tail}</span>`;
  if (source === "env") return `<span class="tag done">🌱 env slot${tail}</span>`;
  if (source === "secret_file") return `<span class="tag done">🗝️ .secrets${tail}</span>`;
  return `<span class="tag waiting">未配置 key</span>`;
}

function renderProviders() {
  const el = $("#providers");
  if (!STATE.providers.length) { el.innerHTML = `<div class="empty">还没有配置任何供应商。</div>`; return; }
  el.innerHTML = STATE.providers.map(p => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(p.name)}</span>
        ${keySourceLabel(p)}
      </div>
      <div class="row-sub">
        base_url：${esc(p.base_url || "(未设置)")}<br>
        模型：${esc(p.model || "(未设置)")} ${p.key_label ? "· 标签 " + esc(p.key_label) : ""}
        ${p.env_slot ? `<br>env slot：<code>${esc(p.env_slot)}</code>${p.env_slot_present ? "（已检测）" : ""}` : ""}
      </div>
      <div class="cap-tags">${(p.tags || []).map(t => `<span class="ct">${esc(t)}</span>`).join("")}</div>
    </div>`).join("");
}


function renderCostPanel() {
  const el = $("#cost-panel");
  if (!el) return;
  const st = STATE.cost_status || {};
  const policy = STATE.cost_policy || {};
  const warnings = st.warnings || [];
  const ledger = STATE.cost_ledger || [];
  const byProvider = Object.entries(st.by_provider || {}).map(([k,v]) => `${esc(k)} ${money(v)}`).join(" · ") || "暂无";
  const byKind = Object.entries(st.by_kind || {}).map(([k,v]) => `${esc(k)} ${money(v)}`).join(" · ") || "暂无";
  el.innerHTML = `
    <div class="row">
      <div class="row-top">
        <span class="row-title">今日估算：${money(st.today_total_usd)} / 日上限 ${money(policy.daily_cap_usd)}</span>
        ${warnings.length ? `<span class="tag waiting">${warnings.length} 条提醒</span>` : `<span class="tag done">预算正常</span>`}
      </div>
      <div class="row-sub">
        provider 分布：${byProvider}<br>
        类型分布：${byKind}<br>
        单次 provider 上限：${money(policy.provider_call_cap_usd)} · 任务上限：${money(policy.task_cap_usd)} · Claude Code 单次上限：${money(policy.cc_run_cap_usd)}
      </div>
      ${warnings.length ? `<div class="preview">${warnings.map(w => esc(w.message || w.kind)).join("\n")}</div>` : ""}
      <div class="row-actions"><button class="btn small" onclick="openCostModal()">调整预算策略</button></div>
    </div>
    <h3 class="sub">最近成本账本</h3>
    ${ledger.length ? ledger.slice(0,5).map(r => `<div class="row"><div class="row-top"><span class="row-title">${esc(r.kind)} ${r.provider_id ? " / " + esc(r.provider_id) : ""}</span><span class="tag idle">≈${money(r.estimated_usd)}</span></div><div class="row-sub">${esc((r.created_at || "").replace("T"," ").slice(0,19))} · ${esc(r.source || "local_estimate")}</div>${r.note ? `<div class="preview">${esc(r.note)}</div>` : ""}</div>`).join("") : `<div class="empty">暂无成本记录。</div>`}
  `;
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

function renderOrchestrations() {
  const el = $("#orchestrations");
  if (!el) return;
  const rows = STATE.orchestrations || [];
  if (!rows.length) { el.innerHTML = `<div class="empty">暂无多 agent 编排批次。</div>`; return; }
  el.innerHTML = rows.map(o => `
    <div class="row">
      <div class="row-top"><span class="row-title">${esc(o.objective || "多 agent 目标")}</span>${statusTag(o.status || "已编排")}</div>
      <div class="row-sub">${esc(o.id)} · ${esc(o.created_at || "")}</div>
      <div>${esc(o.summary || "")}</div>
      <div class="row-sub">子灵：${esc((o.agent_names || []).join("、"))}</div>
      <div class="row-sub">任务：${esc((o.task_ids || []).join(", "))}</div>
    </div>`).join("");
}

function renderInsights() {
  const el = $("#insights");
  if (!el) return;
  const rows = STATE.insights || [];
  if (!rows.length) { el.innerHTML = `<div class="empty">暂无洞察。可点“生成洞察”，或微信发：洞察。</div>`; return; }
  el.innerHTML = rows.map(ins => `
    <div class="row">
      <div class="row-top"><span class="row-title">${esc(ins.summary || "洞察")}</span><span class="tag idle">${esc(ins.source || "local")}</span></div>
      <div class="row-sub">${esc(ins.id)} · ${esc(ins.created_at || "")}</div>
      ${(ins.findings || []).slice(0, 4).map(f => `<div class="mini-line">• <b>${esc(f.title || "")}</b>｜${esc(f.next_action || "")}</div>`).join("")}
    </div>`).join("");
}

function renderSoulFlows() {
  const el = $("#soul-flows");
  if (!el) return;
  const rows = STATE.soul_flows || [];
  if (!rows.length) { el.innerHTML = `<div class="empty">暂无心流。可点“心流回环”，或微信发：心流。</div>`; return; }
  el.innerHTML = rows.map(f => `
    <div class="row">
      <div class="row-top"><span class="row-title">心流 · ${esc(f.trigger || "manual")}</span><span class="tag ok">回环</span></div>
      <div class="row-sub">${esc(f.id)} · ${esc(f.created_at || "")}</div>
      <div class="preview">${esc(f.text || "")}</div>
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
    <label>绑定真实 LingTai agent 地址（可选）</label>
    <input id="na-lingtai" placeholder="例如：mimo-2-5-pro 或某个已存在子灵地址" />
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
    lingtai_address: $("#na-lingtai").value,
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
  const policy = (CATALOG && CATALOG.secret_fallback) || {};
  const kcBanner = kc
    ? `<div class="preview">🔐 真实能力：API key 优先存进 <b>Mac 系统 Keychain</b>；后端不把 key 写入 state.json / 日志 / 界面，只保存来源、后四位和 env slot 名。</div>`
    : `<div class="preview">⚠️ Keychain 当前不可用或已被测试环境禁用。你可以继续保存 base_url / 模型名；若明确接受，可勾选下面的受限 <code>.secrets</code> fallback，把 key 写入 <code>${esc(policy.secret_dir || ".secrets/providers")}/&lt;provider&gt;.key</code>（目录 0700、文件 0600、健康检查只看权限不看值）。也可手动设置只读 env slot：<code>${esc(policy.env_prefix || "LINGTAI_SIMPLE_API_KEY_")}&lt;PROVIDER&gt;</code>。</div>`;
  openModal("🧠 模型 / API 中心", `
    ${kcBanner}
    <label>供应商</label>
    <select id="pv-id" onchange="onProviderPick()">${opts}</select>
    <label>base_url（可编辑）</label>
    <input id="pv-url" placeholder="https://..." />
    <label>模型名（可编辑）</label>
    <input id="pv-model" placeholder="例如：gpt-4o-mini / deepseek-chat / glm-4-flash" />
    <label>API Key（优先进 Keychain；显式勾选时可写受限 .secrets fallback；永不回显、不入库）</label>
    <input id="pv-key" type="password" placeholder="${kc ? "粘贴 key（优先存入系统 Keychain）" : "Keychain 不可用；可勾选受限 .secrets fallback 后保存"}" />
    <label class="checkrow"><input type="checkbox" id="pv-allow-fallback" /> Keychain 写入失败/不可用时，允许写入受限 <code>.secrets</code> fallback（仅本机文件，强制 0700/0600；不用时请勿勾选）</label>
    <label>Key 标签（可选，便于你识别）</label>
    <input id="pv-label" placeholder="例如：圆酱-个人额度" />
    <div class="row-actions">
      <button class="btn primary" onclick="submitProvider()">保存配置${kc ? "（Keychain-first）" : ""}</button>
      <button class="btn small" onclick="checkProviderKey()">检查 key 来源</button>
      <button class="btn small danger" onclick="deleteProviderKey()">删除 Keychain/.secrets key</button>
    </div>

    <hr class="soft" />
    <div class="preview">💸 <b>真实模型调用</b>：下面这一步会通过你保存的 key 向供应商发起 <b>真实网络请求，可能产生费用</b>。其余高危动作中，rollback 已接入本仓库 git Time Machine（确认后真实 reset）；外发 / L3 commit 为真实本地提交确认闸；PR / merge 仍为预览，需下一阶段接入。</div>
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
    api_key: $("#pv-key").value,   // 明文仅用于写 Keychain 或显式受限 fallback，后端不入库
    allow_secret_fallback: $("#pv-allow-fallback")?.checked || false,
    key_label: $("#pv-label").value,
  });
  if (r.ok) {
    $("#pv-key").value = "";
    const src = r.result && r.result.key_source ? r.result.key_source : "none";
    toast(src === "keychain" ? "已保存，key 已进 Keychain 🔐" : (src === "secret_file" ? "已保存，key 已进受限 .secrets 🗝️" : (src === "env" ? "已保存配置，当前使用 env slot 🌱" : "已保存配置（无 key）")));
    render();
  } else toast(r.error || "保存失败");
}
async function checkProviderKey() {
  const r = await api("/api/provider/check_key", { provider_id: $("#pv-id").value });
  if (r.ok) {
    const src = r.result.key_source || "none";
    const pieces = [];
    if (r.result.in_keychain) pieces.push("Keychain");
    if (r.result.env_slot_present) pieces.push("env slot");
    if (r.result.secret_file_present) pieces.push(".secrets");
    toast(src === "none" ? "未找到 key；可用 Keychain / env slot / 受限 .secrets" : "已找到 key 来源：" + pieces.join(" + "));
    render();
  } else toast(r.error || "检查失败");
}
async function deleteProviderKey() {
  if (!confirm("删除本服务可管理的 key？会删除 Mac Keychain 与受限 .secrets 文件；env slot 只能由你在系统环境变量里删除。")) return;
  const r = await api("/api/provider/delete_key", { provider_id: $("#pv-id").value });
  if (r.ok) { toast(r.result.env_slot_present ? "已删除 Keychain/.secrets；但 env slot 仍存在" : "已删除 Keychain/.secrets key"); render(); }
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
    box.innerHTML = `<div class="preview">✅ 真实调用成功 · 模型 ${esc(res.model || "")} · key 来源 ${esc(res.key_source || "未知")} · ${esc(String(res.latency_ms || "?"))}ms
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
    <div class="preview">v0.18 已接入真实微信桥接端点：实际运行时由当前 LingTai WeChat MCP 把圆酱微信消息写入本服务，再原路回复；这里仍可手动提交一条本地测试消息。</div>
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
    <div class="preview">L1 会真实调用本机 Claude Code 只读分析（Read/Grep/Glob）；L2 会在隔离 git worktree 中真实本地改码，验证通过后把 patch 应用回本仓库；两者都可能产生费用且需勾选确认。L3 commit 已接入真实本地执行器；L4 PR / L5 merge 已接入真实 GitHub 执行器；仍必须先进确认队列，批准后才会 push/create PR 或 merge。</div>
    <label>权限等级</label>
    <select id="cc-level">${opts}</select>
    <label>代码任务描述</label>
    <textarea id="cc-desc" placeholder="例如：只读分析仓库结构 / 找 README 中还像 AI 的段落"></textarea>
    <label class="checkline"><input type="checkbox" id="cc-confirm-cost" /> 我确认 L1/L2 会真实调用 Claude Code，可能产生费用；L2 可能修改本仓库文件；不把凭证写进任务描述。</label>
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
    else toast(r.result.status === "完成" ? "Claude Code 运行已完成" : "Claude Code 请求已处理");
    closeModal(); render();
  } else toast(r.error || "失败");
}

function openMultiAgentModal() {
  const opts = (STATE.agents || []).map(a => `<label class="checkline"><input type="checkbox" class="orch-agent" value="${a.id}" /> ${esc(a.name)}｜${esc(a.role)}</label>`).join("") || `<div class="muted">不选也可以：系统会自动创建主控洞察灵、执行落地灵、审校回环灵。</div>`;
  openModal("多 agent / 子灵编排", `
    <p class="hint">真实本地编排：创建或选择多个子灵，把一个目标拆成洞察、执行、审校、回环任务，并记录批次。</p>
    <textarea id="orch-objective" placeholder="例：把 LingTai Simple 做成圆酱专属轻量版灵台，先补多 agent / 洞察 / 心流"></textarea>
    <div class="form-label">选择参与子灵（可不选，自动创建/选择）</div>
    <div class="checks">${opts}</div>
    <button class="btn primary" onclick="submitMultiAgent()">生成多 agent 编排</button>
  `);
}

async function submitMultiAgent() {
  const agent_ids = $$(".orch-agent:checked").map(x => x.value);
  const r = await api("/api/agent/orchestrate", { objective: $("#orch-objective").value, agent_ids });
  if (!r.ok) return toast(r.error || "编排失败");
  STATE = r.state; render(); closeModal(); toast("已生成多 agent 编排");
}

function openInsightModal() {
  openModal("生成洞察", `
    <p class="hint">洞察会读取本地状态：子灵、任务、确认队列、卡点、context 压力；不调用外部模型。</p>
    <textarea id="insight-focus" placeholder="可选焦点：例如，检查专属轻量版灵台还缺什么"></textarea>
    <button class="btn primary" onclick="submitInsight()">生成洞察</button>
  `);
}

async function submitInsight() {
  const r = await api("/api/insight/generate", { focus: $("#insight-focus").value });
  if (!r.ok) return toast(r.error || "洞察失败");
  STATE = r.state; render(); closeModal(); toast("洞察已生成");
}

function openSoulModal() {
  openModal("心流回环", `
    <p class="hint">心流会把当前任务、洞察、确认队列和上下文压力收束成阶段性自省与续功入口。</p>
    <input id="soul-trigger" placeholder="触发原因，例如：圆酱要求认真做专属轻量版灵台" />
    <button class="btn primary" onclick="submitSoul()">生成心流</button>
  `);
}

async function submitSoul() {
  const r = await api("/api/soul/flow", { trigger: $("#soul-trigger").value || "manual" });
  if (!r.ok) return toast(r.error || "心流失败");
  STATE = r.state; render(); closeModal(); toast("心流已生成");
}


function openCostModal() {
  const policy = STATE.cost_policy || {};
  const st = STATE.cost_status || {};
  const ledger = STATE.cost_ledger || [];
  openModal("预算 / 成本面板（本地估算）", `
    <p class="hint">这是本地估算与确认闸：会拦截预计越线的模型调用 / Claude Code 预算预留，并生成短时放行确认项。它不读取供应商真实账单或余额，价格表需要按实际供应商校准。</p>
    <div class="preview">今日估算：${money(st.today_total_usd)} / 日上限 ${money(policy.daily_cap_usd)}\n单次 provider 上限：${money(policy.provider_call_cap_usd)}\n任务上限：${money(policy.task_cap_usd)}\nClaude Code 单次上限：${money(policy.cc_run_cap_usd)}\n长跑提醒阈值：${esc(policy.long_run_seconds || 0)} 秒</div>
    <label>日上限 USD</label><input id="cost-daily" type="number" min="0" step="0.000001" value="${esc(policy.daily_cap_usd ?? 1)}" />
    <label>单次 provider 调用上限 USD</label><input id="cost-provider" type="number" min="0" step="0.000001" value="${esc(policy.provider_call_cap_usd ?? 0.05)}" />
    <label>单任务累计上限 USD</label><input id="cost-task" type="number" min="0" step="0.000001" value="${esc(policy.task_cap_usd ?? 0.25)}" />
    <label>Claude Code 单次预算预留上限 USD</label><input id="cost-cc" type="number" min="0" step="0.000001" value="${esc(policy.cc_run_cap_usd ?? 0.5)}" />
    <label>长跑提醒秒数</label><input id="cost-long" type="number" min="60" step="1" value="${esc(policy.long_run_seconds ?? 900)}" />
    <label class="checkrow"><input type="checkbox" id="cost-enabled" ${policy.enabled !== false ? "checked" : ""} /> 启用预算/成本闸</label>
    <label class="checkrow"><input type="checkbox" id="cost-approval" ${policy.over_cap_requires_approval !== false ? "checked" : ""} /> 越线时必须进入确认队列</label>
    <label class="checkrow"><input type="checkbox" id="cost-reset" /> 同时清空本地成本账本（不影响供应商真实账单）</label>
    <button class="btn primary" onclick="saveCostPolicy()">保存预算策略</button>
    <h3 class="sub">最近账本</h3>
    ${ledger.length ? ledger.slice(0,12).map(r => `<div class="row"><div class="row-top"><span class="row-title">${esc(r.kind)} ${r.provider_id ? " / " + esc(r.provider_id) : ""}</span><span class="tag idle">≈${money(r.estimated_usd)}</span></div><div class="row-sub">${esc(r.created_at || "")} · ${esc(r.source || "")}</div></div>`).join("") : `<div class="empty">暂无成本记录。</div>`}
  `);
}

async function saveCostPolicy() {
  const r = await api("/api/cost/policy", {
    daily_cap_usd: $("#cost-daily").value,
    provider_call_cap_usd: $("#cost-provider").value,
    task_cap_usd: $("#cost-task").value,
    cc_run_cap_usd: $("#cost-cc").value,
    long_run_seconds: $("#cost-long").value,
    enabled: $("#cost-enabled").checked,
    over_cap_requires_approval: $("#cost-approval").checked,
    reset_ledger: $("#cost-reset").checked,
  });
  if (r.ok) { toast("已保存预算/成本策略"); closeModal(); render(); }
  else toast(r.error || "保存失败");
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



async function openLingTaiRuntimeModal(taskId = '', presetAddress = '') {
  let data = { agents: [] };
  try {
    const res = await fetch('/api/lingtai/agents');
    data = await res.json();
  } catch (_) {}
  const taskOptions = (STATE.tasks || []).map(t =>
    `<option value="${esc(t.id)}" ${t.id === taskId ? "selected" : ""}>${esc(t.agent_name)} · ${esc((t.description || '').slice(0, 60))}</option>`
  ).join("");
  const agentOptions = (data.agents || []).map(a =>
    `<option value="${esc(a.address)}" ${a.address === presetAddress ? "selected" : ""}>${esc(a.address)} · ${esc(a.agent_name || '')} · ${esc(a.state || '')}</option>`
  ).join("");
  openModal("📮 派到真实 LingTai agent（内部邮箱）", `
    <div class="preview">v0.18 真实能力：把任务写入 <code>.lingtai/&lt;sender&gt;/mailbox/outbox</code>，由 kernel mailman 投递给真实 agent。不是 mock；会唤醒/占用真实 agent。</div>
    <label>选择本地任务</label>
    <select id="lt-task"><option value="">（手写任务，不绑定本地任务）</option>${taskOptions}</select>
    <label>真实 LingTai agent 地址</label>
    <select id="lt-address-select"><option value="">手动输入</option>${agentOptions}</select>
    <input id="lt-address" placeholder="例如：mimo-2-5-pro" value="${esc(presetAddress || '')}" />
    <label>补充说明（可选；留空则使用任务内容）</label>
    <textarea id="lt-message" placeholder="要交给真实 agent 的任务内容"></textarea>
    <label><input id="lt-confirm" type="checkbox" /> 我确认这是一次真实 LingTai 内部邮箱派发，会唤醒/占用真实 agent</label>
    <button class="btn primary" onclick="submitLingTaiDispatch()">写入真实 outbox</button>
  `);
  const sel = document.getElementById('lt-address-select');
  sel?.addEventListener('change', () => { if (sel.value) document.getElementById('lt-address').value = sel.value; });
}

async function submitLingTaiDispatch() {
  const address = document.getElementById('lt-address').value || document.getElementById('lt-address-select').value;
  const r = await api('/api/lingtai/dispatch', {
    task_id: document.getElementById('lt-task').value,
    address,
    message: document.getElementById('lt-message').value,
    confirm_dispatch: document.getElementById('lt-confirm').checked,
  });
  if (r.ok) { toast('已写入真实 LingTai outbox'); closeModal(); render(); }
  else toast(r.error || '真实派发失败');
}

async function collectLingTaiReplies() {
  const r = await api('/api/lingtai/collect', {});
  if (r.ok) { toast(`已回收 ${r.result.collected || 0} 条真实回复`); render(); }
  else toast(r.error || '回收失败');
}

async function openLingTaiLifecycleModal() {
  let data = { agents: [] };
  try { const res = await fetch('/api/lingtai/agents'); data = await res.json(); } catch (_) {}
  const agentOptions = (data.agents || []).map(a =>
    `<option value="${esc(a.address)}">${esc(a.address)} · ${esc(a.agent_name || '')} · ${a.alive ? 'alive' : 'not live'} · ${esc(a.state || '')}</option>`
  ).join('');
  openModal('⚙ 真实 LingTai 生命周期动作', `
    <div class="preview">这些会作用于真实 LingTai agent。lull/suspend/interrupt/clear 会写入对应 signal 文件；cpr 会尝试用 lingtai-agent run 重启。所有动作先进入确认队列；不提供文件删除或 nirvana。</div>
    <label>真实 LingTai agent</label>
    <select id="lt-life-address"><option value="">请选择</option>${agentOptions}</select>
    <label>动作</label>
    <select id="lt-life-action">
      <option value="lull">lull：入睡（仍可被邮件唤醒）</option>
      <option value="suspend">suspend：挂起/停止进程</option>
      <option value="interrupt">interrupt：中断当前轮</option>
      <option value="clear">clear：强制凝蜕/清上下文</option>
      <option value="cpr">cpr：复苏已停 agent</option>
    </select>
    <button class="btn warn" onclick="requestLingTaiLifecycle()">加入确认队列</button>
  `);
}

async function requestLingTaiLifecycle() {
  const r = await api('/api/lingtai/lifecycle/request', {
    address: document.getElementById('lt-life-address').value,
    action: document.getElementById('lt-life-action').value,
  });
  if (r.ok) { toast('已加入确认队列'); closeModal(); render(); }
  else toast(r.error || '加入确认队列失败');
}

async function openLingTaiAvatarModal() {
  let data = { agents: [] };
  try { const res = await fetch('/api/lingtai/agents'); data = await res.json(); } catch (_) {}
  const agentOptions = (data.agents || []).map(a =>
    `<option value="${esc(a.address)}" ${a.address === 'mimo-2-5-pro' ? 'selected' : ''}>${esc(a.address)} · ${esc(a.agent_name || '')}</option>`
  ).join('');
  openModal('🧬 创建真实 LingTai avatar', `
    <div class="preview">v0.18 真实能力：确认后会在同一个 .lingtai 网络下创建 peer agent 目录，复制并净化模板 init.json，写入 .prompt，然后启动 lingtai-agent run。先只开放 shallow；不继承微信/Telegram/IMAP addon，避免重复 poller；不会删除任何既有 agent。</div>
    <label>avatar 名称 / 地址（单段，不能有空格或斜杠）</label>
    <input id="lt-avatar-name" placeholder="例如：research-helper 或 nutrition_scribe" />
    <label>模板 agent</label>
    <select id="lt-avatar-template"><option value="mimo-2-5-pro">mimo-2-5-pro</option>${agentOptions}</select>
    <label>mission：这个 avatar 要长期负责什么</label>
    <textarea id="lt-avatar-mission" rows="5" placeholder="写清楚它的职责、边界、完成后如何汇报。mission 太短会被拒绝。"></textarea>
    <label>可选 comment</label>
    <input id="lt-avatar-comment" placeholder="例如：圆酱轻量版灵台子灵" />
    <label class="check"><input type="checkbox" id="lt-avatar-confirm" /> 我确认这不是测试，会创建并启动真实 LingTai agent</label>
    <button class="btn warn" onclick="requestLingTaiAvatar()">加入确认队列</button>
  `);
}

async function requestLingTaiAvatar() {
  const r = await api('/api/lingtai/avatar/request', {
    name: document.getElementById('lt-avatar-name').value,
    template_address: document.getElementById('lt-avatar-template').value,
    mission: document.getElementById('lt-avatar-mission').value,
    comment: document.getElementById('lt-avatar-comment').value,
    confirm_mission: document.getElementById('lt-avatar-confirm').checked,
  });
  if (r.ok) { toast('真实 avatar spawn 已加入确认队列'); closeModal(); render(); }
  else toast(r.error || '加入 avatar 确认队列失败');
}


async function openLingTaiBindModal() {
  let data = { agents: [] };
  try { const res = await fetch('/api/lingtai/agents'); data = await res.json(); } catch (_) {}
  const agentOptions = (data.agents || []).map(a =>
    `<option value="${esc(a.address)}">${esc(a.address)} · ${esc(a.agent_name || '')} · ${a.alive ? 'alive' : 'not live'} · ${esc(a.state || '')}</option>`
  ).join('');
  openModal('🔗 绑定既有真实 LingTai agent', `
    <div class="preview">v0.18 真实管理能力：把同网已有真实 agent 绑定成 Simple 本地卡片，方便派发/回收/生命周期管理。此操作只改 Simple 本地状态，不启动、不删除真实 agent。</div>
    <label>真实 LingTai agent</label>
    <select id="lt-bind-address-select"><option value="">手动输入</option>${agentOptions}</select>
    <input id="lt-bind-address" placeholder="例如：mimo-2-5-pro 或某个 avatar 地址" />
    <label>本地显示名称（可选）</label>
    <input id="lt-bind-name" placeholder="留空则使用真实 agent 名称" />
    <label>本地角色说明（可选）</label>
    <input id="lt-bind-role" placeholder="例如：资料整理 / 审校 / 代码苦力" />
    <button class="btn primary" onclick="submitLingTaiBind()">绑定为 Simple 本地卡片</button>
  `);
  const sel = document.getElementById('lt-bind-address-select');
  sel?.addEventListener('change', () => { if (sel.value) document.getElementById('lt-bind-address').value = sel.value; });
}

async function submitLingTaiBind() {
  const r = await api('/api/lingtai/avatar/bind', {
    address: document.getElementById('lt-bind-address').value || document.getElementById('lt-bind-address-select').value,
    name: document.getElementById('lt-bind-name').value,
    role: document.getElementById('lt-bind-role').value,
  });
  if (r.ok) { toast('已绑定真实 LingTai agent'); closeModal(); render(); }
  else toast(r.error || '绑定失败');
}

async function openLingTaiRetireModal() {
  let data = { agents: [] };
  try { const res = await fetch('/api/lingtai/agents'); data = await res.json(); } catch (_) {}
  const realBound = (STATE.agents || []).filter(a => a.lingtai_address);
  const localOptions = realBound.map(a =>
    `<option value="${esc(a.id)}" data-address="${esc(a.lingtai_address)}">${esc(a.name)} · ${esc(a.lingtai_address)} · ${esc(a.status || '')}</option>`
  ).join('');
  const agentOptions = (data.agents || []).map(a =>
    `<option value="${esc(a.address)}">${esc(a.address)} · ${esc(a.agent_name || '')} · ${a.alive ? 'alive' : 'not live'}</option>`
  ).join('');
  openModal('🌙 退休/解绑真实 avatar（不删除目录）', `
    <div class="preview">v0.18 安全语义：退休/解绑不会删除真实 agent 目录，不会 nirvana；只把 Simple 本地卡片标为已退休。可选写入 sleep/suspend signal，让真实 agent 入睡或停止进程。</div>
    <label>已绑定本地卡片</label>
    <select id="lt-retire-local"><option value="">不选本地卡片，手动选地址</option>${localOptions}</select>
    <label>真实 LingTai agent 地址</label>
    <select id="lt-retire-address-select"><option value="">手动输入</option>${agentOptions}</select>
    <input id="lt-retire-address" placeholder="例如：research-helper" />
    <label>退休后动作</label>
    <select id="lt-retire-action">
      <option value="none">none：只在 Simple 中退休/解绑，不碰真实进程</option>
      <option value="lull">lull：额外写 .sleep，让 agent 入睡（可被邮件唤醒）</option>
      <option value="suspend">suspend：额外写 .suspend，停止进程</option>
    </select>
    <label>交接备注（可选）</label>
    <textarea id="lt-retire-note" rows="3" placeholder="记录为什么退休、后续如何恢复或接手。"></textarea>
    <button class="btn warn" onclick="submitLingTaiRetire()">加入确认队列</button>
  `);
  const localSel = document.getElementById('lt-retire-local');
  localSel?.addEventListener('change', () => {
    const opt = localSel.selectedOptions && localSel.selectedOptions[0];
    if (opt && opt.dataset.address) document.getElementById('lt-retire-address').value = opt.dataset.address;
  });
  const addrSel = document.getElementById('lt-retire-address-select');
  addrSel?.addEventListener('change', () => { if (addrSel.value) document.getElementById('lt-retire-address').value = addrSel.value; });
}

async function submitLingTaiRetire() {
  const r = await api('/api/lingtai/avatar/retire', {
    agent_id: document.getElementById('lt-retire-local').value,
    address: document.getElementById('lt-retire-address').value || document.getElementById('lt-retire-address-select').value,
    retire_action: document.getElementById('lt-retire-action').value,
    note: document.getElementById('lt-retire-note').value,
  });
  if (r.ok) { toast('退休/解绑已加入确认队列'); closeModal(); render(); }
  else toast(r.error || '退休/解绑失败');
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
  const sv = h.secret_vault || {};
  const svSummary = sv.summary || {};
  const riskRows = (sv.risks || []).map(r => `
    <div class="row"><div class="row-top"><span class="row-title">${esc(r.location || "")} · ${esc(r.kind || "")}</span><span class="tag ${r.severity === "high" ? "danger" : "waiting"}">${esc(r.severity || "")}</span></div><div class="row-desc">${esc(r.field_path || (r.line ? "line " + r.line : ""))}</div><div class="row-desc">${esc(r.action || "")}</div></div>`).join("") || '<div class="preview">未发现高置信明文 key 风险。</div>';
  const warnRows = (sv.warnings || []).map(w => `<div class="row"><div class="row-top"><span class="row-title">${esc(w.kind || "warning")}</span><span class="tag waiting">${esc(w.severity || "info")}</span></div><div class="row-desc">${esc(w.location || (w.env_names || []).join(", ") || "")}</div><div class="row-desc">${esc(w.action || "")}</div></div>`).join("");
  openModal("🩺 健康检查 / Self-check", `
    <div class="preview">版本：${esc(h.version)} · 地址：${esc(h.host)}:${esc(String(h.port))} · 总体：${h.ok ? "OK" : "FAIL"}</div>
    ${rows}
    <h3>🔐 Secret Vault 明文风险扫描</h3>
    <div class="preview">策略：${esc(sv.policy || "")}<br>扫描文件：${esc(String(svSummary.files_scanned || 0))} · 高风险：${esc(String(svSummary.high || 0))} · 中风险：${esc(String(svSummary.medium || 0))} · 警告：${esc(String(svSummary.warnings || 0))}</div>
    ${riskRows}
    ${warnRows}
    <div class="preview">边界：${esc((h.boundaries || []).join(" / "))}</div>
  `);
}

function openDocsModal() {
  openModal("📖 怎么看这个原型", `
    <div class="preview">这是圆酱专属轻量版灵台 <b>v0.18 — 真实 LingTai 内部邮箱派发里程碑</b>。真实能力逐步接入：<b>模型 API 已真实可用</b>（key 进 Mac Keychain，可发真实请求）；<b>Rollback / Time Machine 已真实接入本仓库 git 快照与确认后 reset</b>；<b>微信入口已通过现有 LingTai WeChat MCP 做真实桥接</b>；Claude Code L1 只读分析、L2 本地改码与 L3 本地 commit 已接入；L4 PR / L5 merge 已接入真实 GitHub 确认闸。本地 Python 服务只是其中一个组件，后续会继续接完整 LingTai runtime/mailbox/skills/memory 与 Mac 应用外壳。</div>
    <ol>
      <li>点「模型 / API 中心」，保存某个供应商的 key（会进系统 Keychain）。</li>
      <li>勾选「我已知道这是真实调用、可能产生费用」后点「▶ 运行真实模型测试」。</li>
      <li>点「新建一个灵」创建子灵；用「本地记录任务」「微信入口任务」体验编排。</li>
      <li>敏感动作进入「确认队列」，先预览；rollback、Claude Code L1 只读分析、L2 本地改码已是真实链路；L3 commit 已接入；L4 PR / L5 merge 已真实接入确认闸。</li>
      <li>点「一键收功」生成可返回的阶段小结。</li>
    </ol>
    <div class="preview">Mac 双击启动：运行目录里的「启动圆酱灵台.command」。</div>
  `);
}


async function refreshLingTaiMemory() {
  const r = await api("/api/lingtai/memory/scan", {});
  if (r.ok) { await refresh(); toast("已刷新真实记忆/技能只读索引"); }
  else toast(r.error || "刷新失败");
}

async function openLingTaiMemoryModal() {
  const mem = await fetch("/api/lingtai/memory").then(r => r.json());
  if (!mem.ok) {
    openModal("真实记忆/技能索引", `<div class="preview danger">${esc(mem.error || "未找到真实 LingTai agent 目录")}</div>`);
    return;
  }
  openModal("真实 LingTai 记忆 / 技能索引（只读）", `
    <p class="hint">这是对真实 agent durable stores 的只读索引，不会读取 secrets/mailbox/logs。点击“只读打开”只返回截断文本，方便普通用户知道这个灵记住了什么、会什么。</p>
    <div class="preview">agent：${esc(mem.agent_dir)}<br>network：${esc(mem.network_dir || "")}</div>
    ${memoryRows(mem.pad, "Pad / 心印入口")}
    ${memoryRows(mem.knowledge, "Knowledge / 私有知识")}
    ${memoryRows(mem.skills, "Skills / 技能")}
    ${memoryRows(mem.summaries, "Molt summaries / 凝蜕摘要")}
  `);
}

async function readLingTaiMemory(path) {
  const r = await api("/api/lingtai/memory/read", { path, max_chars: 10000 });
  if (!r.ok) { toast(r.error || "读取失败"); return; }
  const f = r.result || r.file;
  openModal("只读文件预览", `
    <div class="preview">${esc(f.path)}<br>${f.truncated ? "已截断显示" : "全文显示"} · ${esc(String(f.size || 0))} chars</div>
    <pre class="codeblock">${esc(f.content || "")}</pre>
  `);
}


async function openArchitectureModal() {
  const res = await fetch("/api/architecture/status");
  const a = await res.json();
  const summary = a.summary || {};
  const tagClass = (st) => st === "done" ? "done" : (st === "missing" ? "danger" : "waiting");
  const label = (st) => st === "done" ? "Done / 已跑通" : (st === "missing" ? "Missing / 未接入" : "Partial / 部分接入");
  const rows = (a.items || []).map(it => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(it.id)} · ${esc(it.module)}</span>
        <span class="tag ${tagClass(it.status)}">${label(it.status)}</span>
      </div>
      <div class="row-desc"><b>要求：</b>${esc(it.requirement)}</div>
      <div class="row-desc"><b>证据：</b>${esc(it.evidence)}</div>
      <div class="row-desc"><b>缺口：</b>${esc(it.gap || "无")}</div>
      <div class="row-desc"><b>测试：</b>${esc(it.test || "")}</div>
      <div class="row-desc muted">来源：${esc(it.source || "")}</div>
    </div>`).join("");
  const next = (a.next_recommended_work || []).map(x => `<li>${esc(x)}</li>`).join("");
  openModal("📋 架构验收表 / Acceptance Matrix", `
    <div class="preview">
      版本：${esc(a.version)} · 来源：${esc(a.source)}<br>
      总项：${summary.total || 0} · Done ${summary.done || 0} · Partial ${summary.partial || 0} · Missing ${summary.missing || 0}<br>
      规则：${esc(summary.rule || "")}
    </div>
    ${rows}
    <h3 class="sub">下一批优先补齐</h3>
    <ol>${next}</ol>
  `);
}

// ---------- 绑定 ----------
const ACTIONS = {
  "new-agent": openNewAgentModal,
  "assign-task": () => openTaskModal(),
  "multi-agent": openMultiAgentModal,
  "insight": openInsightModal,
  "soul": openSoulModal,
  "lingtai-runtime": () => openLingTaiRuntimeModal(),
  "lingtai-memory": openLingTaiMemoryModal,
  "wechat": openWechatModal,
  "models": openModelsModal,
  "cc": openCCModal,
  "cost": openCostModal,
  "approvals": openApprovalsModal,
  "shougong": openShougongModal,
  "rollback": openRollbackModal,
  "load-demo": loadDemoState,
  "health": openHealthModal,
  "architecture": openArchitectureModal,
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
window.openCostModal = openCostModal;
window.saveCostPolicy = saveCostPolicy;
window.quickAssign = quickAssign;
window.submitNewAgent = submitNewAgent;
window.submitTask = submitTask;
window.submitMultiAgent = submitMultiAgent;
window.submitInsight = submitInsight;
window.submitSoul = submitSoul;
window.submitProvider = submitProvider;
window.checkProviderKey = checkProviderKey;
window.deleteProviderKey = deleteProviderKey;
window.submitModelTest = submitModelTest;
window.onProviderPick = onProviderPick;
window.submitWechatModal = submitWechatModal;
window.submitCC = submitCC;
window.copyShougong = copyShougong;
window.requestRollback = requestRollback;
