/* 圆酱专属轻量版灵台 v0 — 前端逻辑（纯原生 JS，无依赖） */

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
  if (!STATE.wechat_inbox.length) { el.innerHTML = `<div class="empty">微信队列为空。试着在上面输入一条任务。</div>`; return; }
  el.innerHTML = STATE.wechat_inbox.map(w => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">💬 ${esc(w.text)}</span>
        ${statusTag(w.status)}
      </div>
      <div class="row-sub">
        ${esc(w.ack)}<br>
        阶段：${(w.stages || []).map(esc).join(" → ")}<br>
        承接：${esc(w.assignee)}${w.result ? "<br>回复（mock）：" + esc(w.result) : ""}
      </div>
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
        <button class="btn ok small" onclick="approval('${a.id}','approve')">确认（mock 执行）</button>
        <button class="btn danger small" onclick="approval('${a.id}','deny')">拒绝</button>
      </div>` : ""}
    </div>`).join("");
}

function renderProviders() {
  const el = $("#providers");
  if (!STATE.providers.length) { el.innerHTML = `<div class="empty">还没有配置任何供应商。</div>`; return; }
  el.innerHTML = STATE.providers.map(p => `
    <div class="row">
      <div class="row-top">
        <span class="row-title">${esc(p.name)}</span>
        ${p.configured ? `<span class="tag done">已配置${p.key_last4 ? " ····" + esc(p.key_last4) : ""}</span>` : `<span class="tag waiting">未配置</span>`}
      </div>
      <div class="row-sub">
        base_url：${esc(p.base_url || "(未设置)")}<br>
        模型：${esc(p.model || "(未设置)")} ${p.key_label ? "· 标签 " + esc(p.key_label) : ""}
      </div>
      <div class="cap-tags">${(p.tags || []).map(t => `<span class="ct">${esc(t)}</span>`).join("")}</div>
    </div>`).join("");
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
  if (r.ok) toast(decision === "approve" ? "已确认（mock 执行）" : "已拒绝");
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
  openModal("📨 给灵派任务", `
    <label>派给哪个灵</label>
    <select id="tk-agent">${opts}</select>
    <label>任务内容（一句话）</label>
    <textarea id="tk-desc" placeholder="例如：读这个仓库的 README 并总结要点"></textarea>
    <label>风险等级</label>
    <select id="tk-risk">
      <option value="low">普通（只读/本地，自动 mock 完成）</option>
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
    toast(r.result && r.result.status === "等确认" ? "敏感任务已进确认队列" : "已派活并完成（mock）");
    closeModal(); render();
  } else toast(r.error || "派活失败");
}

function openModelsModal() {
  const opts = CATALOG.providers.map(p => `<option value="${p.id}" data-url="${esc(p.default_base_url)}">${esc(p.name)}</option>`).join("");
  openModal("🧠 模型 / API 中心", `
    <div class="preview">安全：不保存明文 key。只记录「已配置」+ 可选后四位。日志/界面不回显 key。</div>
    <label>供应商</label>
    <select id="pv-id" onchange="onProviderPick()">${opts}</select>
    <label>base_url</label>
    <input id="pv-url" placeholder="https://..." />
    <label>模型名</label>
    <input id="pv-model" placeholder="例如：gpt-4o / deepseek-chat / glm-4" />
    <label>API Key（仅本地，仅取后四位，不回显、不外发）</label>
    <input id="pv-key" type="password" placeholder="粘贴 key（不会被保存为明文）" />
    <label>Key 标签（可选，便于你识别）</label>
    <input id="pv-label" placeholder="例如：圆酱-个人额度" />
    <button class="btn primary" onclick="submitProvider()">保存配置（脱敏）</button>
  `);
  onProviderPick();
}
function onProviderPick() {
  const sel = $("#pv-id");
  const url = sel.options[sel.selectedIndex].getAttribute("data-url");
  $("#pv-url").value = url || "";
}
async function submitProvider() {
  const r = await api("/api/provider/save", {
    provider_id: $("#pv-id").value,
    base_url: $("#pv-url").value,
    model: $("#pv-model").value,
    api_key: $("#pv-key").value,   // 仅用于后四位，后端不存明文
    key_label: $("#pv-label").value,
  });
  if (r.ok) { toast("已保存供应商（key 已脱敏）"); closeModal(); render(); }
  else toast(r.error || "保存失败");
}

function openWechatModal() {
  openModal("💬 微信入口任务（模拟）", `
    <div class="preview">不会真实收发微信。仅演示：ACK → 排队 → 执行 → 完成 / 敏感进确认队列。</div>
    <label>模拟一条微信任务</label>
    <textarea id="wx-modal-input" placeholder="例如：让代码苦力改个 README，但不要提交"></textarea>
    <button class="btn primary" onclick="submitWechatModal()">发到微信队列</button>
  `);
}
async function submitWechatModal() {
  const text = $("#wx-modal-input").value;
  const r = await api("/api/wechat/submit", { text });
  if (r.ok) { toast("微信任务已 ACK 并入队"); closeModal(); render(); }
  else toast(r.error || "提交失败");
}

function openCCModal() {
  const opts = CATALOG.cc_levels.map(l =>
    `<option value="${l.level}">${l.level} · ${esc(l.label)}${l.needs_approval ? "（需确认）" : "（可直接）"}</option>`).join("");
  openModal("🛠️ Claude Code 苦力", `
    <div class="preview">不会真实调用 Claude Code。只读分析直接 mock 完成；其余进确认队列。merge 必须显式确认。</div>
    <label>权限等级</label>
    <select id="cc-level">${opts}</select>
    <label>代码任务描述</label>
    <textarea id="cc-desc" placeholder="例如：分析仓库结构 / 改 README / 开 PR"></textarea>
    <button class="btn primary" onclick="submitCC()">派代码苦力</button>
  `);
}
async function submitCC() {
  const r = await api("/api/cc/request", {
    level: $("#cc-level").value,
    description: $("#cc-desc").value,
  });
  if (r.ok) {
    if (r.result.queued_approval) toast("已进确认队列（敏感代码动作）");
    else toast("只读分析已完成（mock）");
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
  const snaps = data.snapshots.map(s => `
    <div class="row">
      <div class="row-top"><span class="row-title">${esc(s.label)}</span><span class="tag idle">${esc(s.id)}</span></div>
      <div class="row-sub">创建：${esc((s.created_at || "").slice(0, 19).replace("T", " "))}</div>
      <div class="preview">${esc(s.diff_preview)}</div>
      <div class="row-actions">
        <button class="btn small danger" onclick="requestRollback('${s.id}')">回退（进确认队列预览）</button>
      </div>
    </div>`).join("");
  openModal("⏪ 时间机器 / Rollback（mock）", `
    <div class="preview">${esc(data.note)}</div>
    ${snaps}
  `);
}
async function requestRollback(id) {
  const r = await api("/api/rollback/request", { snapshot_id: id });
  if (r.ok) { toast("已进确认队列：回退预览（不会真实 reset）"); closeModal(); render(); }
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
    <div class="preview">这是圆酱专属轻量版灵台 v0.2：先把复杂灵台能力变成可点击 GUI。当前所有执行都是 mock，不会外发、不真实调用 API、不真实改码。</div>
    <ol>
      <li>点「加载示例状态」看完整样子。</li>
      <li>点「新建一个灵」创建子灵。</li>
      <li>点「给灵派任务」或「微信入口任务」模拟派活。</li>
      <li>敏感动作会进入「确认队列」，先预览再确认/拒绝。</li>
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
    if (r.ok) { $("#wx-input").value = ""; toast("微信任务已 ACK 并入队"); render(); }
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
window.onProviderPick = onProviderPick;
window.submitWechatModal = submitWechatModal;
window.submitCC = submitCC;
window.copyShougong = copyShougong;
window.requestRollback = requestRollback;
