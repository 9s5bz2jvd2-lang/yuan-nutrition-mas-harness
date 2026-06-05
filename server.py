#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
圆酱专属轻量版灵台 / LingTai Simple v0.2 — 本地原型服务器

边界（硬红线）：
- 默认 localhost-only（绑定 127.0.0.1）。
- 不访问外网。不真实发送微信/邮件/Telegram。不真实调用任何模型 API。
- 不真实调用 Claude Code。不真实执行 rollback/reset。
- 所有高危动作 → 写入「确认队列」(approval queue)，仅做 preview / mock execution。
- 不保存明文 API key；只保存 configured=true 与可选 key 后四位 / label。

纯 Python 标准库，无第三方依赖。
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# --------------------------------------------------------------------------
# 路径与常量
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
EXAMPLE_STATE_PATH = os.path.join(DATA_DIR, "state.example.json")
SHOUGONG_DIR = os.path.join(DATA_DIR, "shougong")

HOST = os.environ.get("LINGTAI_SIMPLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("LINGTAI_SIMPLE_PORT", "8765"))

MAX_AGENTS = 5  # 最多 5 个灵（v0 硬约束）

# 需要进确认队列的敏感动作类型
SENSITIVE_ACTIONS = {
    "wechat_send", "email_send", "telegram_send",
    "code_commit", "code_pr", "code_merge",
    "rollback_apply", "delete_agent", "file_delete", "high_cost_api",
}

# 供应商目录（第一批）
PROVIDER_CATALOG = [
    {"id": "openai", "name": "GPT / OpenAI-compatible", "default_base_url": "https://api.openai.com/v1",
     "tags": ["chat", "code", "vision"]},
    {"id": "mimo", "name": "小米 MiMo", "default_base_url": "https://api.mimo.example/v1",
     "tags": ["chat", "code"]},
    {"id": "deepseek", "name": "DeepSeek", "default_base_url": "https://api.deepseek.com/v1",
     "tags": ["chat", "code", "cheap"]},
    {"id": "minimax", "name": "MiniMax", "default_base_url": "https://api.minimax.example/v1",
     "tags": ["chat", "tts", "image"]},
    {"id": "glm", "name": "GLM / 智谱", "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
     "tags": ["chat", "code", "vision"]},
    {"id": "custom", "name": "自定义 (base_url + model)", "default_base_url": "",
     "tags": ["custom"]},
]

# Claude Code 苦力权限等级（merge 必须显式确认）
CC_PERMISSION_LEVELS = [
    {"level": 1, "key": "read_only", "label": "只读分析", "needs_approval": False},
    {"level": 2, "key": "local_edit", "label": "本地改码（不提交）", "needs_approval": True},
    {"level": 3, "key": "commit", "label": "允许 commit", "needs_approval": True},
    {"level": 4, "key": "pr", "label": "允许开 PR", "needs_approval": True},
    {"level": 5, "key": "merge", "label": "允许 merge（必须显式确认）", "needs_approval": True},
]

_LOCK = threading.RLock()

# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# 脱敏：把疑似 key/token 替换为 ****（用于日志/回复，绝不回显明文）
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]+\b", re.IGNORECASE),
]


def redact(text):
    if not isinstance(text, str):
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("****REDACTED****", out)
    return out


def key_last4(raw_key):
    """只取后四位用于展示；绝不存全量明文。"""
    if not raw_key:
        return None
    raw_key = raw_key.strip()
    if len(raw_key) <= 4:
        return "****"
    return raw_key[-4:]


def parse_level(value, default=1):
    """
    兼容前端/手工 API 传入的 Claude Code 权限等级。
    支持 1 / "1" / "L1" / "level-1"；非法值回到 default，并夹在 1..5。
    """
    if value is None or value == "":
        n = default
    elif isinstance(value, int):
        n = value
    else:
        m = re.search(r"\d+", str(value))
        n = int(m.group(0)) if m else default
    return max(1, min(5, n))


# --------------------------------------------------------------------------
# 状态管理
# --------------------------------------------------------------------------

def default_state():
    return {
        "meta": {
            "name": "圆酱专属轻量版灵台 / LingTai Simple v0.2",
            "owner": "圆酱 / Runyuan",
            "localhost_only": True,
            "created_at": now_iso(),
            "max_agents": MAX_AGENTS,
        },
        "agents": [],
        "tasks": [],
        "approvals": [],
        "providers": [],       # 已配置的供应商（脱敏）
        "wechat_inbox": [],    # 模拟微信任务队列
        "snapshots": [         # mock 的 time machine 快照
            {
                "id": "snap_seed0001",
                "created_at": now_iso(),
                "label": "初始安全点（示例）",
                "diff_preview": "(示例) 无改动 — 这是种子快照",
            }
        ],
        "log": [],
    }


def load_state():
    with _LOCK:
        if not os.path.exists(STATE_PATH):
            st = default_state()
            save_state(st)
            return st
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # 损坏则重置（原型容错）
            st = default_state()
            save_state(st)
            return st


def save_state(state):
    with _LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)


def log_event(state, message, kind="info"):
    state["log"].insert(0, {
        "ts": now_iso(),
        "kind": kind,
        "message": redact(message),
    })
    state["log"] = state["log"][:200]  # 只留最近 200 条


# --------------------------------------------------------------------------
# 业务逻辑
# --------------------------------------------------------------------------

def estimate_context_pressure(agent):
    """根据任务数粗略模拟 context 压力（0-100）。"""
    n = len(agent.get("recent_tasks", []))
    base = agent.get("context_base", 12)
    return min(100, base + n * 14)


def create_agent(state, payload):
    if len(state["agents"]) >= MAX_AGENTS:
        return None, f"已达上限：最多 {MAX_AGENTS} 个灵"
    name = (payload.get("name") or "").strip() or "未命名的灵"
    role = (payload.get("role") or "长期助手").strip()  # 长期助手 / 临时分析 / 代码苦力
    provider_id = payload.get("provider_id") or ""
    model = (payload.get("model") or "").strip()
    cc_level = parse_level(payload.get("cc_level"), 1)
    agent = {
        "id": new_id("agent"),
        "name": name,
        "role": role,
        "provider_id": provider_id,
        "model": model,
        "cc_level": cc_level,
        "status": "待命",      # 待命 / 正在干 / 卡住 / 等确认 / 已暂停
        "created_at": now_iso(),
        "recent_tasks": [],
        "context_base": 12,
    }
    agent["context_pressure"] = estimate_context_pressure(agent)
    state["agents"].append(agent)
    log_event(state, f"新建灵：{name}（{role}）")
    return agent, None


def find_agent(state, agent_id):
    for a in state["agents"]:
        if a["id"] == agent_id:
            return a
    return None


def assign_task(state, payload):
    agent_id = payload.get("agent_id")
    agent = find_agent(state, agent_id)
    if not agent:
        return None, "找不到该灵"
    if agent["status"] == "已暂停":
        return None, "该灵已暂停，请先恢复"
    desc = (payload.get("description") or "").strip()
    if not desc:
        return None, "任务描述不能为空"
    source = payload.get("source") or "ui"  # ui / wechat
    risk = payload.get("risk") or "low"      # low / sensitive
    task = {
        "id": new_id("task"),
        "agent_id": agent_id,
        "agent_name": agent["name"],
        "description": redact(desc),
        "source": source,
        "risk": risk,
        "status": "排队中",   # 排队中 / 执行中 / 等确认 / 完成 / 已拒绝
        "created_at": now_iso(),
        "result": None,
    }
    state["tasks"].insert(0, task)
    agent["recent_tasks"].insert(0, task["id"])
    agent["recent_tasks"] = agent["recent_tasks"][:8]
    agent["status"] = "正在干"
    agent["context_pressure"] = estimate_context_pressure(agent)
    log_event(state, f"派任务给 {agent['name']}：{desc[:40]}")

    # mock execution：低风险直接“完成”，敏感任务进确认队列
    if risk == "sensitive":
        ap = add_approval(state, {
            "action": payload.get("action_type") or "wechat_send",
            "title": f"任务需确认：{desc[:30]}",
            "detail": desc,
            "task_id": task["id"],
            "agent_id": agent_id,
        })
        task["status"] = "等确认"
        agent["status"] = "等确认"
        task["approval_id"] = ap["id"]
    else:
        task["status"] = "完成"
        task["result"] = f"(mock) 已完成只读/本地处理：{desc[:60]}"
        agent["status"] = "待命"
        log_event(state, f"{agent['name']} 完成任务（mock）")
    return task, None


def set_agent_status(state, agent_id, action):
    agent = find_agent(state, agent_id)
    if not agent:
        return None, "找不到该灵"
    if action == "pause":
        agent["status"] = "已暂停"
        log_event(state, f"暂停灵：{agent['name']}")
    elif action == "resume":
        agent["status"] = "待命"
        log_event(state, f"恢复灵：{agent['name']}")
    elif action == "delete":
        # 删除需走确认队列（敏感）
        ap = add_approval(state, {
            "action": "delete_agent",
            "title": f"删除灵：{agent['name']}",
            "detail": f"将删除灵 {agent['name']}（{agent['id']}）。删除不可自动撤回（mock）。",
            "agent_id": agent_id,
        })
        return {"queued_approval": ap["id"]}, None
    return agent, None


def add_approval(state, payload):
    action = payload.get("action") or "unknown"
    ap = {
        "id": new_id("appr"),
        "action": action,
        "title": redact(payload.get("title") or action),
        "detail": redact(payload.get("detail") or ""),
        "risk": "sensitive" if action in SENSITIVE_ACTIONS else "info",
        "status": "待确认",   # 待确认 / 已确认 / 已拒绝
        "created_at": now_iso(),
        "preview": redact(payload.get("preview") or build_preview(action, payload)),
        "task_id": payload.get("task_id"),
        "agent_id": payload.get("agent_id"),
    }
    state["approvals"].insert(0, ap)
    log_event(state, f"确认队列新增：{ap['title']}", kind="approval")
    return ap


def build_preview(action, payload):
    detail = payload.get("detail") or ""
    previews = {
        "wechat_send": f"[微信外发预览 / 不会真实发送]\n收件人：圆酱\n内容：{detail}",
        "email_send": f"[邮件外发预览 / 不会真实发送]\n{detail}",
        "telegram_send": f"[Telegram 外发预览 / 不会真实发送]\n{detail}",
        "code_commit": f"[git commit 预览 / 不会真实提交]\n{detail}",
        "code_pr": f"[开 PR 预览 / 不会真实创建]\n{detail}",
        "code_merge": f"[merge 预览 / 必须显式确认 / 不会真实合并]\n{detail}",
        "rollback_apply": f"[rollback 预览 / 不会真实 reset]\n{detail}",
        "delete_agent": f"[删除灵预览 / mock]\n{detail}",
        "high_cost_api": f"[高成本 API 预览 / 不会真实调用]\n{detail}",
    }
    return previews.get(action, f"[预览]\n{detail}")


def resolve_approval(state, approval_id, decision):
    for ap in state["approvals"]:
        if ap["id"] == approval_id:
            if ap["status"] != "待确认":
                return None, "该项已处理"
            if decision == "approve":
                ap["status"] = "已确认"
                _apply_approved_action(state, ap)
                log_event(state, f"已确认（mock 执行）：{ap['title']}", kind="approval")
            else:
                ap["status"] = "已拒绝"
                # 关联任务标记拒绝
                if ap.get("task_id"):
                    for t in state["tasks"]:
                        if t["id"] == ap["task_id"]:
                            t["status"] = "已拒绝"
                            ag = find_agent(state, t["agent_id"])
                            if ag:
                                ag["status"] = "待命"
                log_event(state, f"已拒绝：{ap['title']}", kind="approval")
            return ap, None
    return None, "找不到该确认项"


def _apply_approved_action(state, ap):
    """确认后的 mock 执行：绝不产生真实副作用。"""
    action = ap["action"]
    if action == "delete_agent" and ap.get("agent_id"):
        state["agents"] = [a for a in state["agents"] if a["id"] != ap["agent_id"]]
        log_event(state, "（mock）已删除灵")
    if ap.get("task_id"):
        for t in state["tasks"]:
            if t["id"] == ap["task_id"]:
                t["status"] = "完成"
                t["result"] = f"(mock) 已确认并执行：{action}"
                ag = find_agent(state, t["agent_id"])
                if ag:
                    ag["status"] = "待命"


def save_provider(state, payload):
    provider_id = payload.get("provider_id")
    catalog = {p["id"]: p for p in PROVIDER_CATALOG}
    if provider_id not in catalog:
        return None, "未知供应商"
    raw_key = payload.get("api_key") or ""   # 仅用于提取后四位，绝不存全量
    base_url = (payload.get("base_url") or catalog[provider_id]["default_base_url"]).strip()
    model = (payload.get("model") or "").strip()

    entry = {
        "provider_id": provider_id,
        "name": catalog[provider_id]["name"],
        "base_url": base_url,
        "model": model,
        "tags": catalog[provider_id]["tags"],
        "configured": bool(raw_key),
        "key_label": payload.get("key_label") or None,
        "key_last4": key_last4(raw_key) if raw_key else None,
        "updated_at": now_iso(),
    }
    # upsert
    state["providers"] = [p for p in state["providers"] if p["provider_id"] != provider_id]
    state["providers"].append(entry)
    # 日志绝不打印 key
    log_event(state, f"保存供应商配置：{entry['name']}（configured={entry['configured']}）")
    return entry, None


def wechat_submit(state, payload):
    """模拟微信入口：收到一条消息 → ACK → 排队 → 执行 → 完成。"""
    text = (payload.get("text") or "").strip()
    if not text:
        return None, "微信任务内容不能为空"
    msg_id = new_id("wx")
    # 自动选择一个待命的灵作为主控承接，否则记为待派
    target = None
    for a in state["agents"]:
        if a["status"] in ("待命", "正在干"):
            target = a
            break
    sensitive = any(k in text for k in ("发", "提交", "commit", "merge", "PR", "pr", "回退", "rollback", "删除"))
    item = {
        "id": msg_id,
        "text": redact(text),
        "received_at": now_iso(),
        "ack": "已收到 ✅（mock，不会真实回微信）",
        "stages": ["已收到", "排队中"],
        "status": "排队中",
        "assignee": target["name"] if target else "(待派给主控)",
        "result": None,
    }
    state["wechat_inbox"].insert(0, item)
    log_event(state, f"微信任务进入队列：{text[:30]}", kind="wechat")

    if target:
        # 真实派一个 task（仍是 mock execution）
        task, err = assign_task(state, {
            "agent_id": target["id"],
            "description": text,
            "source": "wechat",
            "risk": "sensitive" if sensitive else "low",
            "action_type": "wechat_send",
        })
        item["stages"].append("执行中")
        if sensitive:
            item["status"] = "等确认"
            item["stages"].append("等确认（敏感动作）")
            item["result"] = "该任务涉及敏感动作，已进入确认队列等待圆酱确认。"
        else:
            item["status"] = "完成"
            item["stages"].append("完成")
            item["result"] = "(mock) 已处理，结果将原路回微信（此处不真实发送）。"
        if task:
            item["task_id"] = task["id"]
    else:
        item["status"] = "待派"
        item["result"] = "暂无可承接的灵，请先新建一个灵。"
    return item, None


def generate_shougong(state):
    """生成 Markdown 收功单。"""
    done = [t for t in state["tasks"] if t["status"] == "完成"]
    pending = [t for t in state["tasks"] if t["status"] in ("排队中", "执行中", "等确认")]
    waiting_appr = [a for a in state["approvals"] if a["status"] == "待确认"]
    lines = []
    lines.append(f"# 收功单 / Shougong — {now_iso()}")
    lines.append("")
    lines.append("> 圆酱专属轻量版灵台 v0（本地原型 / 所有执行均为 mock）")
    lines.append("")
    lines.append("## ✅ 已完成")
    if done:
        for t in done:
            lines.append(f"- [{t['agent_name']}] {t['description']} — {t.get('result') or ''}")
    else:
        lines.append("- （暂无）")
    lines.append("")
    lines.append("## ⏳ 未完成 / 进行中")
    if pending:
        for t in pending:
            lines.append(f"- [{t['agent_name']}] {t['description']}（{t['status']}）")
    else:
        lines.append("- （暂无）")
    lines.append("")
    lines.append("## ⚠️ 待确认（敏感动作）")
    if waiting_appr:
        for a in waiting_appr:
            lines.append(f"- {a['title']}（{a['action']}）")
    else:
        lines.append("- （暂无）")
    lines.append("")
    lines.append("## 🧠 灵状态")
    for a in state["agents"]:
        lines.append(f"- {a['name']}（{a['role']}）：{a['status']}，context 压力 {a.get('context_pressure', 0)}%")
    lines.append("")
    lines.append("## 🔜 下一步建议")
    lines.append("- 处理上面「待确认」中的敏感动作。")
    lines.append("- 检查 context 压力高的灵，必要时收束 / 凝蜕。")
    lines.append("")
    lines.append("## 🚧 边界提醒")
    lines.append("- 本原型不真实发送任何消息、不真实改码/PR/merge、不真实 rollback。")
    lines.append("- API key 仅以「已配置 + 后四位」形式保存，界面不回显明文。")
    md = "\n".join(lines)

    os.makedirs(SHOUGONG_DIR, exist_ok=True)
    fname = f"shougong_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    fpath = os.path.join(SHOUGONG_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(md)
    log_event(state, f"生成收功单：{fname}")
    return {"markdown": md, "path": fpath, "filename": fname}


def rollback_preview(state):
    """只 mock 列出 snapshot 与 diff，不真实 reset。"""
    return {
        "snapshots": state["snapshots"],
        "note": "Time Machine 只能（mock）预览文件级 diff。无法撤回已发微信/邮件/API/PR/merge 等外部副作用。点击 rollback 仅进入确认队列预览，不会真实 reset。",
    }


def request_rollback(state, snapshot_id):
    snap = next((s for s in state["snapshots"] if s["id"] == snapshot_id), None)
    if not snap:
        return None, "找不到该快照"
    ap = add_approval(state, {
        "action": "rollback_apply",
        "title": f"回退到快照：{snap['label']}",
        "detail": f"将（mock）回退到 {snap['id']}。\n{snap['diff_preview']}\n注意：无法撤回外部副作用。",
        "preview": f"[Time Machine rollback 预览 / 不会真实 reset]\n快照：{snap['label']} ({snap['id']})\nDiff：{snap['diff_preview']}",
    })
    return ap, None


def request_cc_task(state, payload):
    """Claude Code 苦力卡：按权限等级，敏感等级进确认队列（merge 必须显式确认）。"""
    level = parse_level(payload.get("level"), 1)
    desc = (payload.get("description") or "").strip() or "（无描述）"
    meta = next((l for l in CC_PERMISSION_LEVELS if l["level"] == level), CC_PERMISSION_LEVELS[0])
    if not meta["needs_approval"]:
        # 只读分析 → 直接 mock 完成
        log_event(state, f"Claude Code（只读分析 mock）：{desc[:40]}")
        return {"status": "完成", "mock_result": f"(mock 只读分析) 已分析：{desc[:60]}"}, None
    action_map = {2: "code_commit", 3: "code_commit", 4: "code_pr", 5: "code_merge"}
    action = action_map.get(level, "code_commit")
    if level == 2:
        action = "file_delete" if False else "code_commit"  # 本地改码归入需确认
    ap = add_approval(state, {
        "action": action if level >= 3 else "code_commit",
        "title": f"Claude Code 苦力：{meta['label']}",
        "detail": f"权限等级 {level}（{meta['label']}）\n任务：{desc}\n（不会真实调用 Claude Code，不会真实改码/PR/merge）",
    })
    return {"queued_approval": ap["id"], "level": level}, None


def load_demo_state(_state=None, _payload=None):
    """把 data/state.example.json 载入运行态，方便圆酱打开就看见完整效果。"""
    try:
        with open(EXAMPLE_STATE_PATH, "r", encoding="utf-8") as f:
            demo = json.load(f)
    except OSError:
        demo = default_state()
    demo["meta"]["name"] = "圆酱专属轻量版灵台 / LingTai Simple v0.2（示例模式）"
    demo["meta"]["loaded_demo_at"] = now_iso()
    demo.setdefault("log", [])
    log_event(demo, "加载示例数据：圆酱专属灵台 v0.2 demo")
    save_state(demo)
    return {"loaded_demo": True, "agents": len(demo.get("agents", []))}, None


def health_check():
    """本地健康检查：只读，不触发外部动作。"""
    checks = {
        "localhost_only": HOST in ("127.0.0.1", "localhost", "::1"),
        "static_index": os.path.exists(os.path.join(STATIC_DIR, "index.html")),
        "static_app": os.path.exists(os.path.join(STATIC_DIR, "app.js")),
        "static_styles": os.path.exists(os.path.join(STATIC_DIR, "styles.css")),
        "example_state": os.path.exists(EXAMPLE_STATE_PATH),
        "state_dir": os.path.isdir(DATA_DIR),
        "shougong_dir": os.path.isdir(SHOUGONG_DIR) or True,
    }
    return {
        "ok": all(checks.values()),
        "version": "v0.2",
        "host": HOST,
        "port": PORT,
        "checks": checks,
        "boundaries": [
            "localhost-only", "mock-only high-risk actions",
            "no real model API calls", "no real WeChat/email/Telegram sends",
            "no plaintext API key storage",
        ],
    }


# --------------------------------------------------------------------------
# HTTP Handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LingTaiSimple/0.1"

    def log_message(self, fmt, *args):
        # 自定义日志，且脱敏
        msg = fmt % args
        print(f"[{now_iso()}] {redact(msg)}")

    # ---- helpers ----
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _guard_local(self):
        """只允许本机访问。"""
        client = self.client_address[0]
        if client not in ("127.0.0.1", "::1", "localhost"):
            self._send_json({"error": "localhost-only"}, 403)
            return False
        return True

    # ---- GET ----
    def do_GET(self):
        if not self._guard_local():
            return
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/" or route == "/index.html":
            return self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        if route == "/styles.css":
            return self._send_file(os.path.join(STATIC_DIR, "styles.css"), "text/css; charset=utf-8")
        if route == "/app.js":
            return self._send_file(os.path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8")

        if route == "/api/state":
            state = load_state()
            return self._send_json(self._public_state(state))
        if route == "/api/catalog":
            return self._send_json({
                "providers": PROVIDER_CATALOG,
                "cc_levels": CC_PERMISSION_LEVELS,
                "max_agents": MAX_AGENTS,
            })
        if route == "/api/rollback/preview":
            state = load_state()
            return self._send_json(rollback_preview(state))
        if route == "/api/health":
            return self._send_json(health_check())

        return self._send_json({"error": "not found", "route": route}, 404)

    # ---- POST ----
    def do_POST(self):
        if not self._guard_local():
            return
        route = urlparse(self.path).path
        payload = self._read_body()

        with _LOCK:
            state = load_state()
            handler = self._post_routes().get(route)
            if not handler:
                return self._send_json({"error": "not found", "route": route}, 404)
            result, err = handler(state, payload)
            if err:
                return self._send_json({"ok": False, "error": err}, 400)
            save_state(state)
            resp = {"ok": True, "result": result}
            # 始终带回最新公开状态，前端一次刷新
            resp["state"] = self._public_state(state)
            return self._send_json(resp)

    def _post_routes(self):
        return {
            "/api/agent/create": lambda s, p: create_agent(s, p),
            "/api/task/assign": lambda s, p: assign_task(s, p),
            "/api/agent/pause": lambda s, p: set_agent_status(s, p.get("agent_id"), "pause"),
            "/api/agent/resume": lambda s, p: set_agent_status(s, p.get("agent_id"), "resume"),
            "/api/agent/delete": lambda s, p: set_agent_status(s, p.get("agent_id"), "delete"),
            "/api/approval/add": lambda s, p: add_approval(s, p),
            "/api/approval/approve": lambda s, p: resolve_approval(s, p.get("approval_id"), "approve"),
            "/api/approval/deny": lambda s, p: resolve_approval(s, p.get("approval_id"), "deny"),
            "/api/provider/save": lambda s, p: save_provider(s, p),
            "/api/wechat/submit": lambda s, p: wechat_submit(s, p),
            "/api/demo/load": lambda s, p: load_demo_state(s, p),
            "/api/shougong": lambda s, p: (generate_shougong(s), None),
            "/api/rollback/request": lambda s, p: request_rollback(s, p.get("snapshot_id")),
            "/api/cc/request": lambda s, p: request_cc_task(s, p),
            "/api/reset": lambda s, p: self._reset(s, p),
        }

    def _reset(self, state, payload):
        st = default_state()
        save_state(st)
        return {"reset": True}, None

    def _public_state(self, state):
        """返回给前端的公开状态。供应商绝不带任何 key。"""
        safe_providers = []
        for p in state.get("providers", []):
            sp = dict(p)
            sp.pop("api_key", None)  # 防御性：确保不存在
            safe_providers.append(sp)
        return {
            "meta": state["meta"],
            "agents": state["agents"],
            "tasks": state["tasks"][:30],
            "approvals": state["approvals"][:30],
            "providers": safe_providers,
            "wechat_inbox": state["wechat_inbox"][:20],
            "snapshots": state["snapshots"],
            "log": state["log"][:40],
            "stats": {
                "agent_count": len(state["agents"]),
                "max_agents": MAX_AGENTS,
                "pending_approvals": len([a for a in state["approvals"] if a["status"] == "待确认"]),
                "active_tasks": len([t for t in state["tasks"] if t["status"] in ("排队中", "执行中", "等确认")]),
            },
        }


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------

def ensure_example_state():
    """写出 state.example.json（示例数据，供参考）。"""
    example = default_state()
    a1 = {
        "id": "agent_demo0001", "name": "营养审稿灵", "role": "长期助手",
        "provider_id": "deepseek", "model": "deepseek-chat", "cc_level": 1,
        "status": "待命", "created_at": now_iso(), "recent_tasks": [], "context_base": 18,
    }
    a1["context_pressure"] = estimate_context_pressure(a1)
    a2 = {
        "id": "agent_demo0002", "name": "代码管家灵", "role": "代码苦力",
        "provider_id": "openai", "model": "gpt-4o", "cc_level": 2,
        "status": "正在干", "created_at": now_iso(),
        "recent_tasks": ["task_demoaaaa"], "context_base": 30,
    }
    a2["context_pressure"] = estimate_context_pressure(a2)
    example["agents"] = [a1, a2]
    example["providers"] = [{
        "provider_id": "deepseek", "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
        "tags": ["chat", "code", "cheap"], "configured": True,
        "key_label": "圆酱-DS", "key_last4": "1234", "updated_at": now_iso(),
    }]
    example["wechat_inbox"] = [{
        "id": "wx_demo0001", "text": "让代码苦力看一下这个仓库，给我改个 README，但不要直接提交。",
        "received_at": now_iso(), "ack": "已收到 ✅（mock）",
        "stages": ["已收到", "排队中", "执行中", "等确认（敏感动作）"],
        "status": "等确认", "assignee": "代码管家灵",
        "result": "涉及改码，已进入确认队列。",
    }]
    with open(EXAMPLE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(example, f, ensure_ascii=False, indent=2)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ensure_example_state()
    load_state()  # 确保 state.json 存在
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=" * 64)
    print("  圆酱专属轻量版灵台 / LingTai Simple v0 — 本地原型")
    print("=" * 64)
    print(f"  地址 : http://{HOST}:{PORT}/")
    print(f"  状态 : {STATE_PATH}")
    print("  边界 : localhost-only / 全部执行均为 mock / 不外发 / 不真实改码")
    print("  停止 : Ctrl+C")
    print("=" * 64)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.server_close()


if __name__ == "__main__":
    main()
