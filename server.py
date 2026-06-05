#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
圆酱专属轻量版灵台 / LingTai Simple v0.9 — 本地原型服务器

边界（硬红线）：
- 默认 localhost-only（绑定 127.0.0.1）。
- v0.9 已真实接入：Keychain 密钥保险柜、OpenAI-compatible 模型 API 调用、git Time Machine / rollback、微信桥接入口、Claude Code L1 只读分析、L2 本地改码、L3 本地 commit，以及 L4/L5 GitHub PR/merge 执行闸。
- 微信桥接不启动第二个 poller、不保存微信凭证；真实收发仍由当前 LingTai WeChat MCP 作为唯一桥接者完成。
- Claude Code L1 只读分析与 L2 本地改码已真实接入（需显式确认可能产生费用；L2 会修改本仓库文件）；commit、PR、merge 均已接入确认闸；L4 会真实 push 分支并创建 GitHub PR，L5 会在确认后真实合并指定 PR。
- 不保存明文 API key 到 JSON / 日志 / API 响应；明文 key 只存进 Mac Keychain。

v0.9 的「真实能力」（与 v0.2 的纯 mock 不同）：
- 通过 macOS Security.framework 把 API key 存进系统 Keychain（fallback：清晰报错，绝不落明文）。
- 对 OpenAI-compatible /chat/completions 端点发起**真实**网络请求（需用户在 UI 显式点击，
  并明确标注「可能产生费用」）。
- git Time Machine：创建安全快照、列快照、预览 diff，并在确认队列批准后执行真实 `git reset --hard` 回退。
- 微信桥接入口：当前 LingTai/WeChat MCP 可把真实微信消息 POST 到本服务，本服务写入任务/确认队列并返回可原路回复的 `reply_text`。
- Claude Code worker：L1 显式确认费用后调用本机 `claude --print` 做只读分析；L2 在隔离 git worktree 中允许本地改码，经 py_compile 与高置信秘密扫描后把 patch 应用回本仓库；L3 可在再次确认后创建真实本地 git commit；L4 可在确认后 push 分支并创建 GitHub PR；L5 可在确认后 merge 指定 PR。

Python 标准库 + macOS Security.framework（通过 ctypes 调用，无第三方依赖）。
"""

import json
import os
import re
import shutil
import subprocess
import threading
import ctypes
import ctypes.util
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import tempfile
import time

# --------------------------------------------------------------------------
# 路径与常量
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
EXAMPLE_STATE_PATH = os.path.join(DATA_DIR, "state.example.json")
SHOUGONG_DIR = os.path.join(DATA_DIR, "shougong")
CC_RUN_DIR = os.path.join(DATA_DIR, "cc_runs")
CC_WORKTREE_DIR = os.path.join(tempfile.gettempdir(), "lingtai-simple-cc-worktrees")

HOST = os.environ.get("LINGTAI_SIMPLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("LINGTAI_SIMPLE_PORT", "8765"))

MAX_AGENTS = 5  # 最多 5 个灵（v0 硬约束）

# 需要进确认队列的敏感动作类型
SENSITIVE_ACTIONS = {
    "wechat_send", "email_send", "telegram_send",
    "code_commit", "code_pr", "code_merge",
    "rollback_apply", "delete_agent", "file_delete", "high_cost_api", "sensitive_task",
}

# 供应商目录（OpenAI-compatible /chat/completions）。
# default_model 仅作为 UI 默认填充；base_url / model 均可在界面编辑。
PROVIDER_CATALOG = [
    {"id": "openai", "name": "GPT / OpenAI-compatible", "default_base_url": "https://api.openai.com/v1",
     "default_model": "gpt-4o-mini", "tags": ["chat", "code", "vision"]},
    {"id": "mimo", "name": "小米 MiMo（需填写兼容端点）", "default_base_url": "",
     "default_model": "", "tags": ["chat", "code", "needs-base-url"]},
    {"id": "deepseek", "name": "DeepSeek", "default_base_url": "https://api.deepseek.com/v1",
     "default_model": "deepseek-chat", "tags": ["chat", "code", "cheap"]},
    {"id": "minimax", "name": "MiniMax（需确认兼容端点）", "default_base_url": "",
     "default_model": "", "tags": ["chat", "tts", "image", "needs-base-url"]},
    {"id": "glm", "name": "GLM / 智谱", "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
     "default_model": "glm-4-flash", "tags": ["chat", "code", "vision"]},
    {"id": "custom", "name": "自定义 (base_url + model)", "default_base_url": "",
     "default_model": "", "tags": ["custom"]},
]
PROVIDER_IDS = {p["id"] for p in PROVIDER_CATALOG}

# Keychain 服务名前缀：每个供应商一个 account，便于增删查。
KEYCHAIN_SERVICE = os.environ.get("LINGTAI_SIMPLE_KEYCHAIN_SERVICE", "lingtai-simple")

# 真实模型调用的安全上限（避免误操作烧钱）。
MODEL_CALL_TIMEOUT = 30          # 秒
MODEL_CALL_MAX_TOKENS = 256      # 单次测试回复上限

# git Time Machine / rollback：只在本 repo 内操作，外部副作用无法回滚。
SNAPSHOT_REF_PREFIX = "refs/lingtai-simple/snapshots"
SAFETY_REF_PREFIX = "refs/lingtai-simple/safety"
ROLLBACK_DIFF_MAX_CHARS = 6000

# Claude Code 苦力权限等级（merge 必须显式确认）
CC_PERMISSION_LEVELS = [
    {"level": 1, "key": "read_only", "label": "只读分析", "needs_approval": False},
    {"level": 2, "key": "local_edit", "label": "本地改码（不提交）", "needs_approval": True},
    {"level": 3, "key": "commit", "label": "允许 commit", "needs_approval": True},
    {"level": 4, "key": "pr", "label": "允许开 PR", "needs_approval": True},
    {"level": 5, "key": "merge", "label": "允许 merge（必须显式确认）", "needs_approval": True},
]
CC_RUN_TIMEOUT = 240
CC_MAX_OUTPUT_CHARS = 12000
CC_MAX_BUDGET_USD = os.environ.get("LINGTAI_SIMPLE_CC_MAX_BUDGET_USD", "0.50")
DEMO_TIMESTAMP = "2026-06-05T08:00:00-07:00"
COMMIT_AUTHOR_NAME = os.environ.get("LINGTAI_SIMPLE_COMMIT_AUTHOR_NAME", "Wang Runyuan")
COMMIT_AUTHOR_EMAIL = os.environ.get("LINGTAI_SIMPLE_COMMIT_AUTHOR_EMAIL", "281843989+9s5bz2jvd2-lang@users.noreply.github.com")
GITHUB_EXPECTED_LOGIN = os.environ.get("LINGTAI_SIMPLE_GITHUB_EXPECTED_LOGIN", "9s5bz2jvd2-lang")
_DEFAULT_GH_CONFIG_DIR = "/Users/huangzesen/work/GitHub/lingtai/.worktrees/docs-beginner-work-manual/.gh-runyuan"
GITHUB_CONFIG_DIR = os.environ.get("LINGTAI_SIMPLE_GH_CONFIG_DIR") or (_DEFAULT_GH_CONFIG_DIR if os.path.isdir(_DEFAULT_GH_CONFIG_DIR) else "")
GITHUB_PR_BODY_MAX_CHARS = 6000


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


# --------------------------------------------------------------------------
# Mac Keychain 密钥保险柜
# --------------------------------------------------------------------------
# 设计：明文 API key 只进 macOS 系统 Keychain（generic-password），永不落到
# state.json / 日志 / API 响应。account = provider_id，service = KEYCHAIN_SERVICE。
# 若 `security` CLI 不可用（非 mac / 被裁剪），所有操作返回清晰错误，绝不退化为明文存储。

class KeychainUnavailable(Exception):
    """macOS `security` CLI 不可用时抛出。"""


# Security.framework OSStatus values used here.
ERR_SEC_SUCCESS = 0
ERR_SEC_DUPLICATE_ITEM = -25299
ERR_SEC_ITEM_NOT_FOUND = -25300

_SECURITY = None
_COREFOUNDATION = None

def _load_security_framework():
    """Load macOS Security.framework through ctypes. No shell argv secrets."""
    global _SECURITY, _COREFOUNDATION
    if _SECURITY is not None:
        return _SECURITY, _COREFOUNDATION
    sec_path = ctypes.util.find_library("Security")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not sec_path or not cf_path:
        raise KeychainUnavailable(
            "未找到 macOS Security.framework：本机可能不是 macOS，或 Keychain 不可用。"
            "为安全起见，不会把明文 API key 落到磁盘。"
        )
    sec = ctypes.CDLL(sec_path)
    cf = ctypes.CDLL(cf_path)

    sec.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    ]
    sec.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)
    ]
    sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    sec.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p
    ]
    sec.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    sec.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    sec.SecKeychainItemDelete.restype = ctypes.c_int32
    sec.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    sec.SecKeychainItemFreeContent.restype = ctypes.c_int32
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None

    _SECURITY, _COREFOUNDATION = sec, cf
    return sec, cf


def _release_item(item_ref):
    if item_ref:
        try:
            _load_security_framework()[1].CFRelease(item_ref)
        except Exception:
            pass


def _status_message(status):
    common = {
        ERR_SEC_DUPLICATE_ITEM: "Keychain 已存在同名项目",
        ERR_SEC_ITEM_NOT_FOUND: "Keychain 中未找到该项目",
        -25308: "Keychain 当前不允许交互或被锁定",
        -25293: "Keychain 认证失败",
    }
    return common.get(status, f"OSStatus {status}")


def _keychain_find_item(provider_id, want_password=False):
    sec, _cf = _load_security_framework()
    service = KEYCHAIN_SERVICE.encode("utf-8")
    account = provider_id.encode("utf-8")
    password_len = ctypes.c_uint32(0)
    password_data = ctypes.c_void_p()
    item_ref = ctypes.c_void_p()
    status = sec.SecKeychainFindGenericPassword(
        None, len(service), service, len(account), account,
        ctypes.byref(password_len) if want_password else None,
        ctypes.byref(password_data) if want_password else None,
        ctypes.byref(item_ref),
    )
    if status == ERR_SEC_ITEM_NOT_FOUND:
        return status, None, None
    if status != ERR_SEC_SUCCESS:
        return status, None, None
    password = None
    if want_password and password_data and password_len.value:
        try:
            password = ctypes.string_at(password_data, password_len.value).decode("utf-8")
        finally:
            sec.SecKeychainItemFreeContent(None, password_data)
    return status, item_ref, password


def keychain_available():
    """是否能用 macOS Security.framework Keychain。"""
    try:
        _load_security_framework()
        return True
    except KeychainUnavailable:
        return False


def keychain_set(provider_id, raw_key):
    """把明文 key 写入 Keychain（存在则覆盖）。不经 shell/argv，不记录明文。"""
    sec, _cf = _load_security_framework()
    service = KEYCHAIN_SERVICE.encode("utf-8")
    account = provider_id.encode("utf-8")
    secret = (raw_key or "").encode("utf-8")
    item_ref = ctypes.c_void_p()
    status = sec.SecKeychainAddGenericPassword(
        None, len(service), service, len(account), account,
        len(secret), ctypes.c_char_p(secret), ctypes.byref(item_ref)
    )
    if status == ERR_SEC_SUCCESS:
        _release_item(item_ref)
        return True
    if status == ERR_SEC_DUPLICATE_ITEM:
        find_status, existing_ref, _password = _keychain_find_item(provider_id, want_password=False)
        if find_status != ERR_SEC_SUCCESS or not existing_ref:
            raise KeychainUnavailable(f"更新 Keychain 失败：{_status_message(find_status)}")
        try:
            update_status = sec.SecKeychainItemModifyAttributesAndData(
                existing_ref, None, len(secret), ctypes.c_char_p(secret)
            )
        finally:
            _release_item(existing_ref)
        if update_status == ERR_SEC_SUCCESS:
            return True
        raise KeychainUnavailable(f"更新 Keychain 失败：{_status_message(update_status)}")
    raise KeychainUnavailable(f"写入 Keychain 失败：{_status_message(status)}")


def keychain_get(provider_id):
    """读取明文 key（仅用于真实模型调用时即时取用）。失败返回 None。"""
    status, item_ref, password = _keychain_find_item(provider_id, want_password=True)
    _release_item(item_ref)
    if status != ERR_SEC_SUCCESS:
        return None
    return password or None


def keychain_delete(provider_id):
    """从 Keychain 删除 key。不存在视为已删除。"""
    status, item_ref, _password = _keychain_find_item(provider_id, want_password=False)
    if status == ERR_SEC_ITEM_NOT_FOUND:
        return True
    if status != ERR_SEC_SUCCESS or not item_ref:
        return False
    try:
        return _load_security_framework()[0].SecKeychainItemDelete(item_ref) == ERR_SEC_SUCCESS
    finally:
        _release_item(item_ref)


def keychain_has(provider_id):
    """Keychain 是否存在该供应商的 key（不读出明文）。"""
    status, item_ref, _password = _keychain_find_item(provider_id, want_password=False)
    _release_item(item_ref)
    return status == ERR_SEC_SUCCESS


# --------------------------------------------------------------------------
# 真实模型调用（OpenAI-compatible /chat/completions）
# --------------------------------------------------------------------------
# 这是会产生真实外部副作用（网络请求 + 可能计费）的能力之一；另一个真实本地副作用是 git rollback。
# 必须由 UI 显式触发；key 从 Keychain 即时取用，绝不写入状态/日志/响应。

def _chat_completions_url(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url 为空，无法发起真实调用。")
    # 允许传入已含 /chat/completions 的完整 URL。
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def real_model_call(base_url, model, api_key, prompt, max_tokens=MODEL_CALL_MAX_TOKENS):
    """
    发起一次真实的 chat completion 请求。返回 (result_dict, error_str)。
    成功 result 含：reply（截断的回复文本）、model、usage、latency_ms、http_status。
    绝不在返回值或日志中包含 api_key。
    """
    if not api_key:
        return None, "Keychain 中没有该供应商的 key，请先在「模型 / API 中心」保存 key。"
    if not (model or "").strip():
        return None, "未指定模型名（model）。"
    try:
        url = _chat_completions_url(base_url)
    except ValueError as e:
        return None, str(e)

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a connectivity test. Reply with a short confirmation."},
            {"role": "user", "content": prompt or "Hello! Please reply with one short sentence."},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }).encode("utf-8")

    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    t0 = datetime.now(timezone.utc)
    try:
        with urlopen(req, timeout=MODEL_CALL_TIMEOUT) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        # 脱敏后返回，绝不回显任何可能的凭证片段。
        return None, redact(f"HTTP {e.code}：{detail or e.reason}")
    except URLError as e:
        return None, redact(f"网络错误：{getattr(e, 'reason', e)}")
    except Exception as e:  # 兜底，避免把堆栈里潜在的 key 暴露
        return None, redact(f"调用失败：{e}")

    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"reply": redact(raw[:500]), "model": model,
                "http_status": status, "latency_ms": latency_ms, "usage": None}, None

    reply = ""
    try:
        reply = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        reply = redact(json.dumps(data)[:500])
    return {
        "reply": redact((reply or "").strip()[:1000]),
        "model": data.get("model") or model,
        "http_status": status,
        "latency_ms": latency_ms,
        "usage": data.get("usage"),
    }, None


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
            "name": "圆酱专属轻量版灵台 / LingTai Simple v0.9",
            "owner": "圆酱 / Runyuan",
            "localhost_only": True,
            "created_at": now_iso(),
            "max_agents": MAX_AGENTS,
        },
        "agents": [],
        "tasks": [],
        "approvals": [],
        "providers": [],       # 已配置的供应商（脱敏）
        "wechat_inbox": [],    # 微信入口收到的任务队列（v0.8 支持真实桥接写入）
        "wechat_outbox": [],   # 待桥接者原路发回微信的回复（不由本服务直接轮询/发送，避免双 poller）
        "wechat_bridge": {
            "mode": "lingtai_mcp_bridge",
            "status": "ready",
            "note": "由当前 LingTai 的 WeChat MCP 作为唯一真实收发桥；本服务只提供 localhost 控制端点。",
        },
        "cc_runs": [],          # Claude Code 运行记录（v0.8 真实接入 L1/L2；L3 是确认后本地 commit）
        "snapshots": [],         # 兼容旧字段；真实快照来自 git refs
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
                return normalize_state(json.load(f))
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


def normalize_state(state):
    """兼容旧版本 state.json：补齐 v0.8 新字段，避免升级后丢状态。"""
    base = default_state()
    state.setdefault("meta", base["meta"])
    state["meta"]["name"] = "圆酱专属轻量版灵台 / LingTai Simple v0.9"
    state["meta"]["max_agents"] = MAX_AGENTS
    state.setdefault("agents", [])
    state.setdefault("tasks", [])
    state.setdefault("approvals", [])
    state.setdefault("providers", [])
    state.setdefault("wechat_inbox", [])
    state.setdefault("wechat_outbox", [])
    state.setdefault("wechat_bridge", base["wechat_bridge"])
    state.setdefault("cc_runs", [])
    state.setdefault("snapshots", [])
    state.setdefault("log", [])
    return state


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
    # 部分真实动作需要保留经过验证的机器字段，供确认后执行。不要放明文 secret。
    for k in ("rollback_ref", "rollback_commit", "snapshot_id", "commit_message", "commit_safety_ref", "github_repo", "github_base_branch", "github_head_branch", "github_head_commit", "github_pr_title", "github_pr_body", "github_pr_number", "github_pr_url", "github_merge_method"):
        if payload.get(k):
            ap[k] = str(payload.get(k))
    if payload.get("commit_changed_files"):
        ap["commit_changed_files"] = [str(x) for x in payload.get("commit_changed_files", [])][:120]
    state["approvals"].insert(0, ap)
    log_event(state, f"确认队列新增：{ap['title']}", kind="approval")
    return ap


def build_preview(action, payload):
    detail = payload.get("detail") or ""
    previews = {
        "wechat_send": f"[微信外发预览 / 不会真实发送]\n收件人：圆酱\n内容：{detail}",
        "email_send": f"[邮件外发预览 / 不会真实发送]\n{detail}",
        "telegram_send": f"[Telegram 外发预览 / 不会真实发送]\n{detail}",
        "code_commit": f"[git commit 预览 / 确认后会真实创建本地 commit；不会 push/PR/merge]\n{detail}",
        "code_pr": f"[GitHub PR 预览 / 确认后会真实 push 分支并创建 PR]\n{detail}",
        "code_merge": f"[GitHub merge 预览 / 确认后会真实合并指定 PR]\n{detail}",
        "rollback_apply": f"[rollback 预览 / 确认后会真实 git reset --hard]\n{detail}",
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
                err = _apply_approved_action(state, ap)
                if err:
                    ap["status"] = "执行失败"
                    ap["result"] = err
                    log_event(state, f"确认后执行失败：{ap['title']}（{err[:80]}）", kind="approval")
                else:
                    log_event(state, f"已确认并执行：{ap['title']}", kind="approval")
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
    """确认后的执行。rollback_apply 与 code_commit 会产生真实本地 git 副作用。"""
    action = ap["action"]
    if action == "rollback_apply":
        result, err = rollback_apply_real(state, ap.get("rollback_ref"))
        if err:
            return err
        ap["result"] = result
        return None
    if action == "code_commit":
        result, err = git_commit_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        if ap.get("task_id"):
            for t in state["tasks"]:
                if t["id"] == ap["task_id"]:
                    t["status"] = "完成"
                    t["result"] = f"已创建真实本地 git commit：{result.get('commit_short')}（未 push / 未 PR / 未 merge）"
                    ag = find_agent(state, t["agent_id"])
                    if ag:
                        ag["status"] = "待命"
        return None
    if action == "code_pr":
        result, err = github_pr_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        if ap.get("task_id"):
            for t in state["tasks"]:
                if t["id"] == ap["task_id"]:
                    t["status"] = "完成"
                    t["result"] = f"已真实创建 GitHub PR：{result.get('pr_url')}（未 merge）"
                    ag = find_agent(state, t["agent_id"])
                    if ag:
                        ag["status"] = "待命"
        return None
    if action == "code_merge":
        result, err = github_merge_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        if ap.get("task_id"):
            for t in state["tasks"]:
                if t["id"] == ap["task_id"]:
                    t["status"] = "完成"
                    t["result"] = f"已真实 merge GitHub PR：{result.get('pr_url') or result.get('pr_number')}"
                    ag = find_agent(state, t["agent_id"])
                    if ag:
                        ag["status"] = "待命"
        return None
    if action == "delete_agent" and ap.get("agent_id"):
        state["agents"] = [a for a in state["agents"] if a["id"] != ap["agent_id"]]
        log_event(state, "（本地状态）已删除灵")
    if ap.get("task_id"):
        for t in state["tasks"]:
            if t["id"] == ap["task_id"]:
                t["status"] = "完成"
                if action in ("wechat_send", "email_send", "telegram_send", "sensitive_task"):
                    t["result"] = f"已确认：{action}；当前 v0.8 对该动作仅完成本地确认/记录，尚未接入该动作的真实执行器。"
                else:
                    t["result"] = f"已确认并执行：{action}"
                ag = find_agent(state, t["agent_id"])
                if ag:
                    ag["status"] = "待命"
    return None


def _provider_entry(state, provider_id):
    for p in state.get("providers", []):
        if p["provider_id"] == provider_id:
            return p
    return None


def save_provider(state, payload):
    """保存供应商配置。若带 api_key，则把明文 key 写入 Mac Keychain（不落 state.json）。"""
    provider_id = payload.get("provider_id")
    catalog = {p["id"]: p for p in PROVIDER_CATALOG}
    if provider_id not in catalog:
        return None, "未知供应商"
    raw_key = (payload.get("api_key") or "").strip()   # 仅用于写 Keychain + 取后四位，绝不存进 state
    base_url = (payload.get("base_url") or catalog[provider_id]["default_base_url"]).strip()
    model = (payload.get("model") or "").strip()

    existing = _provider_entry(state, provider_id) or {}
    in_keychain = bool(existing.get("in_keychain"))
    key_last4_val = existing.get("key_last4")

    # 若提供了新 key → 写入 Keychain（失败则整笔失败，绝不退化为明文存储）
    if raw_key:
        if not keychain_available():
            return None, ("无法保存 key：本机无法使用 macOS Security.framework（Keychain 不可用）。"
                          "为防止明文泄露，已拒绝保存。你仍可只保存 base_url / model（不含 key）。")
        try:
            keychain_set(provider_id, raw_key)
        except KeychainUnavailable as e:
            return None, str(e)
        in_keychain = True
        key_last4_val = key_last4(raw_key)

    entry = {
        "provider_id": provider_id,
        "name": catalog[provider_id]["name"],
        "base_url": base_url,
        "model": model,
        "tags": catalog[provider_id]["tags"],
        "configured": in_keychain,
        "in_keychain": in_keychain,           # key 是否存在于 Keychain
        "key_label": payload.get("key_label") or existing.get("key_label") or None,
        "key_last4": key_last4_val,           # 仅展示用的后四位
        "updated_at": now_iso(),
    }
    # 防御性：绝不把明文 key 放进可序列化的 entry
    entry.pop("api_key", None)
    # upsert
    state["providers"] = [p for p in state["providers"] if p["provider_id"] != provider_id]
    state["providers"].append(entry)
    # 日志绝不打印 key
    log_event(state, f"保存供应商配置：{entry['name']}（in_keychain={in_keychain}）")
    return entry, None


def delete_provider_key(state, payload):
    """从 Keychain 删除该供应商的 key，并把状态标记为未配置（保留 base_url / model）。"""
    provider_id = payload.get("provider_id")
    if provider_id not in PROVIDER_IDS:
        return None, "未知供应商"
    if not keychain_available():
        return None, "Keychain 不可用（非 macOS 或无法加载 Security.framework）。"
    keychain_delete(provider_id)  # 不存在视为已删除
    entry = _provider_entry(state, provider_id)
    if entry:
        entry["in_keychain"] = False
        entry["configured"] = False
        entry["key_last4"] = None
        entry["updated_at"] = now_iso()
    log_event(state, f"已从 Keychain 删除 key：{provider_id}")
    return {"provider_id": provider_id, "in_keychain": False}, None


def check_provider_key(state, payload):
    """检查 Keychain 中是否存在该供应商的 key（不读出明文）。同步修正 state 标记。"""
    provider_id = payload.get("provider_id")
    if provider_id not in PROVIDER_IDS:
        return None, "未知供应商"
    if not keychain_available():
        return {"provider_id": provider_id, "keychain_available": False,
                "in_keychain": False,
                "note": "本机无法加载 macOS Security.framework，无法使用 Keychain。"}, None
    present = keychain_has(provider_id)
    entry = _provider_entry(state, provider_id)
    if entry:
        entry["in_keychain"] = present
        entry["configured"] = present
        if not present:
            entry["key_last4"] = None
    return {"provider_id": provider_id, "keychain_available": True,
            "in_keychain": present}, None


def prepare_model_test(state, payload):
    """
    真实模型调用的「锁内准备」阶段：校验 + 从 Keychain 取 key + 解析 base_url/model。
    返回 (call_spec, error)。call_spec 含明文 key，仅供随后（锁外）发起网络请求用，
    绝不写入 state / 日志 / 响应。
    """
    provider_id = payload.get("provider_id")
    if provider_id not in PROVIDER_IDS:
        return None, "未知供应商"
    if not payload.get("confirm_cost"):
        return None, "真实调用可能产生费用，请在界面勾选/确认后再试。"

    entry = _provider_entry(state, provider_id) or {}
    catalog = {p["id"]: p for p in PROVIDER_CATALOG}
    base_url = (payload.get("base_url") or entry.get("base_url")
                or catalog[provider_id]["default_base_url"])
    model = (payload.get("model") or entry.get("model")
             or catalog[provider_id]["default_model"])
    prompt = (payload.get("prompt") or "").strip()

    if not keychain_available():
        return None, "Keychain 不可用（非 macOS 或无法加载 Security.framework），无法取出 key 进行真实调用。"
    api_key = keychain_get(provider_id)
    if not api_key:
        return None, "Keychain 中没有该供应商的 key，请先在「模型 / API 中心」保存 key。"

    log_event(state, f"真实模型调用（可能计费）：{provider_id} / {model}", kind="real_api")
    return {"provider_id": provider_id, "base_url": base_url, "model": model,
            "prompt": prompt, "api_key": api_key}, None


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


def _find_pending_approval(state, approval_id):
    for ap in state.get("approvals", []):
        if ap.get("id") == approval_id and ap.get("status") == "待确认":
            return ap
    return None


def _wechat_outbox_add(state, *, inbound_id, user_id, reply_to_message_id, reply_text, status="ready_for_bridge"):
    item = {
        "id": new_id("wxout"),
        "inbound_id": inbound_id,
        "user_id": user_id,
        "reply_to_message_id": reply_to_message_id,
        "reply_text": redact(reply_text),
        "status": status,  # ready_for_bridge / sent / failed
        "created_at": now_iso(),
        "transport": "lingtai_wechat_mcp_bridge",
    }
    state.setdefault("wechat_outbox", []).insert(0, item)
    state["wechat_outbox"] = state["wechat_outbox"][:50]
    return item


def _bridge_status_text(state):
    pending = [a for a in state.get("approvals", []) if a.get("status") == "待确认"]
    active = [t for t in state.get("tasks", []) if t.get("status") in ("排队中", "执行中", "等确认")]
    agents = state.get("agents", [])
    lines = [
        "圆酱，LingTai Simple v0.9 当前状态：",
        f"- 灵：{len(agents)}/{MAX_AGENTS} 个；待确认：{len(pending)}；进行中/待处理任务：{len(active)}。",
        f"- 已真实接入：微信桥接入口、Keychain、真实模型 API（需费用确认）、git Time Machine/rollback。",
        "- 微信桥接说明：我通过现有 LingTai WeChat MCP 原路回复，不启动第二个微信 poller。",
    ]
    if pending:
        lines.append("\n待确认：")
        for ap in pending[:5]:
            lines.append(f"- {ap['id']}：{ap.get('title','')}（回复：确认 {ap['id']} / 拒绝 {ap['id']}）")
    if state.get("tasks"):
        lines.append("\n最近任务：")
        for t in state["tasks"][:5]:
            lines.append(f"- {t.get('status')}｜{t.get('agent_name','')}｜{t.get('description','')[:40]}")
    return "\n".join(lines)


def _bridge_rollback_list_text(state):
    prev = rollback_preview(state)
    if not prev.get("git_available"):
        return "当前仓库 git 不可用，无法列 Time Machine 快照。"
    snaps = prev.get("snapshots", [])[:8]
    if not snaps:
        return "当前还没有 Time Machine 快照。可以微信发：快照 我的标签"
    lines = ["Time Machine 快照（可微信发：回滚 <id>，随后再确认）："]
    for sp in snaps:
        lines.append(f"- {sp.get('id')}｜{sp.get('short','')}｜{sp.get('created_at','')}｜{sp.get('label','')}")
    if prev.get("dirty"):
        lines.append("\n注意：当前工作区有未提交改动，回滚前会显示确认队列并创建 safety ref。")
    return "\n".join(lines)


def wechat_bridge_incoming(state, payload):
    """真实微信桥接入口。

    设计边界：本服务不直接启动 WeChat poller、也不持有微信凭证；由当前 LingTai agent 的
    WeChat MCP 作为唯一收发桥，把真实收到的消息 POST 到这里，再把返回的 reply_text 原路
    wechat.reply 回去。这样避免第二个 poller 抢消息，同时把 LingTai Simple 的任务/确认/rollback
    状态真实落盘。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        return None, "微信桥接消息不能为空"
    user_id = payload.get("user_id") or ""
    message_id = payload.get("message_id") or payload.get("wechat_message_id") or ""
    sender = payload.get("sender") or payload.get("sender_name") or "圆酱"
    inbound_id = payload.get("inbound_id") or new_id("wxin")
    lower = text.lower()

    item = {
        "id": inbound_id,
        "text": redact(text),
        "received_at": now_iso(),
        "source": "real_wechat_bridge",
        "user_id": user_id,
        "message_id": message_id,
        "sender": sender,
        "ack": "已通过真实微信桥接收到 ✅",
        "stages": ["真实微信收到", "写入 LingTai Simple"],
        "status": "处理中",
        "assignee": "主控桥接",
        "result": None,
    }
    state.setdefault("wechat_inbox", []).insert(0, item)
    state["wechat_inbox"] = state["wechat_inbox"][:50]
    log_event(state, f"真实微信桥接收到：{text[:40]}", kind="wechat")

    reply = None
    # ---- Command routing ----
    if lower in ("状态", "status", "/status", "状态一下"):
        item["status"] = "完成"
        item["stages"].append("状态已生成")
        reply = _bridge_status_text(state)
    elif lower.startswith(("确认 ", "approve ")):
        approval_id = text.split(maxsplit=1)[1].strip()
        ap, err = resolve_approval(state, approval_id, "approve")
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("确认队列处理完成" if not err else "确认失败")
        reply = f"已确认并执行：{approval_id}" if not err else f"确认失败：{err}"
        if ap and ap.get("result"):
            reply += f"\n结果：{ap['result']}"
    elif lower.startswith(("拒绝 ", "deny ")):
        approval_id = text.split(maxsplit=1)[1].strip()
        ap, err = resolve_approval(state, approval_id, "deny")
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("拒绝队列处理完成" if not err else "拒绝失败")
        reply = f"已拒绝：{approval_id}" if not err else f"拒绝失败：{err}"
    elif lower.startswith(("快照", "snapshot")):
        label = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else "wechat-bridge"
        snap, err = create_snapshot(state, {"label": label})
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("Time Machine 快照已创建" if not err else "快照失败")
        reply = (f"已创建 Time Machine 快照：{snap['id']}\nref：{snap['ref']}"
                 if not err else f"创建快照失败：{err}")
    elif lower in ("回滚列表", "rollback list", "snapshots", "快照列表"):
        item["status"] = "完成"
        item["stages"].append("快照列表已生成")
        reply = _bridge_rollback_list_text(state)
    elif lower.startswith(("回滚 ", "rollback ")):
        snapshot_id = text.split(maxsplit=1)[1].strip()
        ap, err = request_rollback(state, snapshot_id)
        item["status"] = "等确认" if not err else "卡住"
        item["stages"].append("rollback 已进入确认队列" if not err else "rollback 请求失败")
        reply = (f"已把 rollback 放入确认队列：{ap['id']}\n请核对后微信回复：确认 {ap['id']}\n边界：只能回滚本仓库 tracked/unignored 文件，不能撤回已发消息/API/PR 等外部副作用。"
                 if not err else f"回滚请求失败：{err}")
    elif lower.startswith(("收功", "shougong", "/shougong")):
        sg = generate_shougong(state)
        item["status"] = "完成"
        item["stages"].append("收功单已生成")
        reply = f"已生成收功单：{sg['path']}\n\n你可以先离屏休息；回来按收功单继续。"
    else:
        # 默认把真实微信消息落入任务队列；如无灵则自动创建主控灵，确保圆酱可直接微信开用。
        target = None
        for a in state.get("agents", []):
            if a.get("status") in ("待命", "正在干"):
                target = a
                break
        if not target:
            target, _ = create_agent(state, {"name": "微信主控灵", "role": "长期助手", "provider_id": "", "model": "", "cc_level": 1})
        sensitive = any(k in text for k in ("发", "提交", "commit", "merge", "PR", "pr", "回滚", "rollback", "删除", "push"))
        task, err = assign_task(state, {
            "agent_id": target["id"],
            "description": text,
            "source": "wechat_bridge",
            "risk": "sensitive" if sensitive else "low",
            "action_type": "sensitive_task" if sensitive else "local_task",
        })
        if err:
            item["status"] = "卡住"
            item["stages"].append("入队失败")
            reply = f"收到，但入队失败：{err}"
        elif task.get("status") == "等确认":
            item["status"] = "等确认"
            item["task_id"] = task["id"]
            item["stages"].append("敏感任务进入确认队列")
            reply = f"收到，已进入 LingTai Simple 任务队列，并因涉及敏感动作进入确认队列：{task.get('approval_id')}。\n请在确认队列核对，或微信回复：确认 {task.get('approval_id')} / 拒绝 {task.get('approval_id')}。"
        else:
            item["status"] = "完成"
            item["task_id"] = task["id"]
            item["stages"].append("任务已记录")
            reply = "收到，已通过真实微信桥接写入 LingTai Simple 任务队列。\n当前 v0.8 会真实记录/编排/确认；rollback 与 Claude Code L1 只读分析已接入；任意外发、commit、merge 等敏感动作都会先进入确认队列。\n可微信发：状态 / 收功 / 快照 <标签> / 回滚列表。"

    item["result"] = reply
    out = _wechat_outbox_add(state, inbound_id=inbound_id, user_id=user_id,
                             reply_to_message_id=message_id, reply_text=reply)
    return {"inbound": item, "outbox": out, "reply_text": reply, "should_reply": True}, None


def wechat_bridge_mark_sent(state, payload):
    outbox_id = payload.get("outbox_id") or payload.get("id")
    sent_message_id = payload.get("sent_message_id") or payload.get("message_id")
    for item in state.setdefault("wechat_outbox", []):
        if item.get("id") == outbox_id:
            item["status"] = "sent"
            item["sent_at"] = now_iso()
            if sent_message_id:
                item["sent_message_id"] = str(sent_message_id)
            log_event(state, f"微信桥接回复已标记发送：{outbox_id}", kind="wechat")
            return item, None
    return None, "找不到该微信 outbox 项"


def generate_shougong(state):
    """生成 Markdown 收功单。"""
    done = [t for t in state["tasks"] if t["status"] == "完成"]
    pending = [t for t in state["tasks"] if t["status"] in ("排队中", "执行中", "等确认")]
    waiting_appr = [a for a in state["approvals"] if a["status"] == "待确认"]
    lines = []
    lines.append(f"# 收功单 / Shougong — {now_iso()}")
    lines.append("")
    lines.append("> 圆酱专属轻量版灵台 v0.8（本地原型 / Keychain、模型 API、git Time Machine、微信桥接入口、Claude Code L1 只读分析、L2 本地改码与 L3 本地 commit 已真实接入；PR/merge 仍在接入中）")
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
    lines.append("- 本原型不真实发送任何消息；Time Machine / rollback、Claude Code L2 本地改码与 L3 本地 commit 已真实接入，但只能作用于本仓库文件，不能撤回外部副作用；PR/merge 仍未接入。")
    lines.append("- API key 仅以「已配置 + 后四位」形式保存，界面不回显明文。")
    md = "\n".join(lines)

    os.makedirs(SHOUGONG_DIR, exist_ok=True)
    fname = f"shougong_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    fpath = os.path.join(SHOUGONG_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(md)
    log_event(state, f"生成收功单：{fname}")
    return {"markdown": md, "path": fpath, "filename": fname}


def _git(args, timeout=10, extra_env=None, check=True):
    """Run git in BASE_DIR with deterministic, non-interactive settings."""
    env = os.environ.copy()
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(["git"] + list(args), cwd=BASE_DIR, env=env,
                          text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "git command failed").strip()
        raise RuntimeError(redact(msg)[:500])
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def _git_available():
    return os.path.isdir(os.path.join(BASE_DIR, ".git")) and shutil.which("git") is not None


def _short_ref(ref):
    return ref.split("/")[-1]


def _bounded(text, limit=ROLLBACK_DIFF_MAX_CHARS):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（已截断，原文 {len(text)} 字符）"


def _validate_lingtai_ref(ref):
    ref = (ref or "").strip()
    if not (ref.startswith(SNAPSHOT_REF_PREFIX + "/") or ref.startswith(SAFETY_REF_PREFIX + "/")):
        return None, "只允许回退到 LingTai Simple 自己创建的 snapshot/safety ref"
    try:
        commit, _, _ = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"])
    except Exception as e:
        return None, f"快照不存在或不是 commit：{e}"
    return commit.strip(), None


def _create_tree_commit_ref(prefix, label):
    """Create a ref commit from the current working tree without moving HEAD/index."""
    if not _git_available():
        raise RuntimeError("当前目录不是 git 仓库，无法创建 Time Machine 快照")
    head, _, _ = _git(["rev-parse", "--verify", "HEAD"])
    safe_label = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff ]+", "-", (label or "snapshot")).strip()[:80] or "snapshot"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ref = f"{prefix}/{stamp}-{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory(prefix="lingtai-simple-index-") as td:
        idx = os.path.join(td, "index")
        env = {"GIT_INDEX_FILE": idx}
        _git(["read-tree", "HEAD"], extra_env=env)
        # Capture tracked modifications and untracked non-ignored files; ignored runtime state stays out.
        _git(["add", "-A", "--", "."], extra_env=env)
        tree, _, _ = _git(["write-tree"], extra_env=env)
        created_at = now_iso()
        message = f"LingTai Simple Time Machine: {safe_label}\n\nCreated-By: yuanjiang-lingtai-simple\nCreated-At: {created_at}\n"
        commit_env = {
            **env,
            "GIT_AUTHOR_NAME": "Yuanjiang LingTai Simple",
            "GIT_AUTHOR_EMAIL": "yuanjiang-lingtai-simple@local",
            "GIT_COMMITTER_NAME": "Yuanjiang LingTai Simple",
            "GIT_COMMITTER_EMAIL": "yuanjiang-lingtai-simple@local",
            "GIT_AUTHOR_DATE": created_at,
            "GIT_COMMITTER_DATE": created_at,
        }
        commit, _, _ = _git(["commit-tree", tree, "-p", head, "-m", message], extra_env=commit_env)
    _git(["update-ref", ref, commit])
    return {
        "id": _short_ref(ref),
        "ref": ref,
        "commit": commit,
        "short_commit": commit[:12],
        "label": safe_label,
        "created_at": now_iso(),
    }


def create_snapshot(state, payload):
    label = (payload.get("label") or "手动安全快照").strip() if isinstance(payload, dict) else "手动安全快照"
    try:
        snap = _create_tree_commit_ref(SNAPSHOT_REF_PREFIX, label)
    except Exception as e:
        return None, f"创建快照失败：{e}"
    log_event(state, f"Time Machine 创建真实快照：{snap['label']} ({snap['short_commit']})", kind="rollback")
    return snap, None


def _list_time_machine_refs():
    if not _git_available():
        return []
    fmt = "%(refname)|%(objectname)|%(creatordate:iso8601)|%(subject)"
    out, _, _ = _git(["for-each-ref", "--sort=-creatordate", f"--format={fmt}",
                      SNAPSHOT_REF_PREFIX, SAFETY_REF_PREFIX], check=False)
    items = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        ref, commit, created_at, subject = parts
        kind = "safety" if ref.startswith(SAFETY_REF_PREFIX + "/") else "snapshot"
        items.append({
            "id": _short_ref(ref),
            "ref": ref,
            "commit": commit,
            "short_commit": commit[:12],
            "created_at": created_at,
            "label": subject.replace("LingTai Simple Time Machine: ", ""),
            "kind": kind,
            "diff_preview": _snapshot_diff_preview(ref),
        })
    return items


def _snapshot_diff_preview(ref):
    commit, err = _validate_lingtai_ref(ref)
    if err:
        return err
    stat, _, _ = _git(["diff", "--stat", commit, "--"], timeout=10, check=False)
    names, _, _ = _git(["diff", "--name-status", commit, "--"], timeout=10, check=False)
    if not stat and not names:
        return "当前工作区与该快照的 tracked 文件一致。"
    return _bounded((stat + "\n" + names).strip())


def rollback_preview(state):
    snapshots = _list_time_machine_refs()
    status, _, _ = _git(["status", "--short"], check=False) if _git_available() else ("", "", 1)
    head, _, _ = _git(["rev-parse", "--short", "HEAD"], check=False) if _git_available() else ("", "", 1)
    return {
        "snapshots": snapshots,
        "git_available": _git_available(),
        "current_head": head,
        "dirty": bool(status.strip()),
        "status_short": _bounded(status, 2000),
        "note": "Time Machine 已真实接入：可创建 git 安全快照、预览当前工作区到快照的 diff，并在确认队列批准后执行真实 git reset --hard。它只能回滚本仓库文件，无法撤回已发微信/邮件/API/PR/merge 等外部副作用。执行 rollback 前会再自动创建 safety 快照。",
    }


def request_rollback(state, snapshot_id):
    snapshots = _list_time_machine_refs()
    snap = next((s for s in snapshots if s["id"] == snapshot_id or s["ref"] == snapshot_id), None)
    if not snap:
        return None, "找不到该快照"
    commit, err = _validate_lingtai_ref(snap["ref"])
    if err:
        return None, err
    ap = add_approval(state, {
        "action": "rollback_apply",
        "title": f"回退到快照：{snap['label']}",
        "detail": f"将真实执行 git reset --hard 到 {snap['short_commit']}。\n{snap['diff_preview']}\n注意：只能回滚本仓库文件，无法撤回外部副作用。执行前会自动创建 safety 快照。",
        "preview": f"[Time Machine rollback 真实预览 / 确认后会 reset]\n快照：{snap['label']} ({snap['id']})\n目标 commit：{commit[:12]}\nDiff：\n{snap['diff_preview']}\n\n外部副作用（已发消息/API/PR/merge）无法撤回。",
        "rollback_ref": snap["ref"],
        "rollback_commit": commit,
        "snapshot_id": snap["id"],
    })
    return ap, None


def rollback_apply_real(state, ref):
    commit, err = _validate_lingtai_ref(ref)
    if err:
        return None, err
    try:
        safety = _create_tree_commit_ref(SAFETY_REF_PREFIX, "rollback-before-current-state")
        _git(["reset", "--hard", commit], timeout=20)
    except Exception as e:
        return None, f"rollback 执行失败：{e}"
    result = {
        "rolled_back_to": commit[:12],
        "target_ref": ref,
        "safety_ref": safety["ref"],
        "safety_commit": safety["short_commit"],
        "external_side_effects_note": "只能回滚本仓库文件；微信/邮件/API/PR/merge 等外部副作用无法撤回。",
    }
    log_event(state, f"Time Machine 已真实 rollback 到 {commit[:12]}；执行前 safety={safety['short_commit']}", kind="rollback")
    return result, None


def _looks_like_secret(text):
    """拒绝把疑似 key/token 送入外部 Claude Code。"""
    if not isinstance(text, str):
        return False
    checks = [
        re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{12,}\b", re.IGNORECASE),
        re.compile(r"\bghp_[A-Za-z0-9_]{12,}\b"),
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
        re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b"),
    ]
    return any(p.search(text) for p in checks)


def claude_code_available():
    return shutil.which("claude") is not None


def _git_changed_paths():
    """Return unignored changed paths in the main repo, including untracked files."""
    changed = set()
    for args in (["diff", "--name-only"], ["diff", "--cached", "--name-only"]):
        out, _, _ = _git(args, timeout=10, check=False)
        for line in out.splitlines():
            if line.strip():
                changed.add(line.strip())
    out, _, _ = _git(["ls-files", "--others", "--exclude-standard"], timeout=10, check=False)
    for line in out.splitlines():
        if line.strip():
            changed.add(line.strip())
    return sorted(changed)


def _sanitize_commit_message(text):
    msg = redact((text or "").strip())
    msg = re.sub(r"\s+", " ", msg).strip()
    if not msg:
        msg = "chore: update LingTai Simple"
    if len(msg) > 180:
        msg = msg[:177].rstrip() + "..."
    if _looks_like_secret(msg):
        return None, "commit message 疑似包含 API key / token；请删除凭证后再提交。"
    return msg, None


def prepare_cc_commit_approval(state, payload):
    """Queue a confirmation-gated real local git commit (L3). No push/PR/merge."""
    if not _git_available():
        return None, "当前目录不是 git 仓库，无法创建真实 commit。"
    desc = (payload.get("description") or "").strip()
    message_source = payload.get("commit_message") or desc or "chore: update LingTai Simple"
    message, err = _sanitize_commit_message(message_source)
    if err:
        return None, err
    changed = _git_changed_paths()
    if not changed:
        return None, "当前仓库没有未提交改动；无需创建 commit。"
    if len(changed) > 120:
        return None, f"改动文件过多（{len(changed)} 个）；为避免误提交，请先缩小范围或人工检查。"
    secret_hits = _high_confidence_secret_hits(BASE_DIR, changed)
    if secret_hits:
        return None, "高置信秘密扫描发现疑似凭证，已拒绝进入 commit 确认队列：" + json.dumps(secret_hits, ensure_ascii=False)
    compile_check = _run_py_compile_check(BASE_DIR)
    if not compile_check.get("ok"):
        return None, "py_compile 未通过，拒绝进入 commit 确认队列：" + compile_check.get("output", "")
    stat, _, _ = _git(["diff", "--stat"], timeout=10, check=False)
    cached_stat, _, _ = _git(["diff", "--cached", "--stat"], timeout=10, check=False)
    detail = "\n".join([
        f"commit message：{message}",
        f"author：{COMMIT_AUTHOR_NAME} <{COMMIT_AUTHOR_EMAIL}>",
        f"changed files（{len(changed)}）：" + ", ".join(changed[:40]) + (" ..." if len(changed) > 40 else ""),
        "验证：py_compile OK；高置信秘密扫描 OK。",
        "边界：确认后只创建本地 git commit；不会 push、不会开 PR、不会 merge，也不能撤销已发生的外部副作用。",
        "diff stat：",
        (stat or cached_stat or "（无 stat；可能只有未跟踪文件）")[:1800],
    ])
    ap = add_approval(state, {
        "action": "code_commit",
        "title": "Claude Code 苦力：允许 commit（真实本地提交）",
        "detail": detail,
        "preview": f"[git commit 预览 / 确认后真实提交]\n{detail}",
        "commit_message": message,
        "commit_changed_files": changed,
    })
    log_event(state, f"真实 commit 已进入确认队列：{message}", kind="git")
    return {"queued_approval": ap["id"], "level": 3, "real_executor": True, "changed_files": changed, "commit_message": message}, None


def git_commit_apply_real(state, ap):
    """Create a real local git commit after explicit approval. Does not push/PR/merge."""
    if not _git_available():
        return None, "当前目录不是 git 仓库，无法创建 commit。"
    message, err = _sanitize_commit_message(ap.get("commit_message") or ap.get("title"))
    if err:
        return None, err
    approved_paths = sorted(str(x) for x in ap.get("commit_changed_files", []) if str(x).strip())
    if not approved_paths:
        return None, "确认项缺少已审阅文件清单；为避免误提交，已拒绝 commit。请重新发起 L3 commit 请求。"
    changed = _git_changed_paths()
    if not changed:
        return None, "确认时仓库已无未提交改动；commit 已取消。"
    if changed != approved_paths:
        return None, "确认时工作区改动与预览时不一致；为避免误提交，已拒绝 commit。请重新查看 diff 后再发起 L3 commit 请求。"
    secret_hits = _high_confidence_secret_hits(BASE_DIR, changed)
    if secret_hits:
        return None, "确认时高置信秘密扫描发现疑似凭证，已拒绝 commit：" + json.dumps(secret_hits, ensure_ascii=False)
    compile_check = _run_py_compile_check(BASE_DIR)
    if not compile_check.get("ok"):
        return None, "确认时 py_compile 未通过，已拒绝 commit：" + compile_check.get("output", "")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    head, _, _ = _git(["rev-parse", "HEAD"], timeout=10)
    safety_ref = f"{SAFETY_REF_PREFIX}/pre-commit-{ts}-{uuid.uuid4().hex[:6]}"
    _git(["update-ref", safety_ref, head], timeout=10)
    try:
        _git(["add", "--", *approved_paths], timeout=30)
        env = {
            "GIT_AUTHOR_NAME": COMMIT_AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": COMMIT_AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": COMMIT_AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": COMMIT_AUTHOR_EMAIL,
        }
        _git(["commit", "-m", message], timeout=60, extra_env=env)
        commit, _, _ = _git(["rev-parse", "HEAD"], timeout=10)
        stat, _, _ = _git(["show", "--stat", "--oneline", "--no-renames", "--format=%h %s", commit], timeout=20, check=False)
    except Exception as e:
        _git(["reset", "--", *approved_paths], timeout=20, check=False)
        return None, f"git commit 失败，已保留工作区改动并取消暂存：{e}"
    result = {
        "commit": commit,
        "commit_short": commit[:7],
        "message": message,
        "author": f"{COMMIT_AUTHOR_NAME} <{COMMIT_AUTHOR_EMAIL}>",
        "changed_files": changed,
        "safety_ref": safety_ref,
        "stat": _bounded(stat, 3000),
        "boundary": "local git commit only; no push, no PR, no merge",
    }
    ap["commit_safety_ref"] = safety_ref
    log_event(state, f"真实本地 commit 已创建：{commit[:7]} {message}", kind="git")
    return result, None



def _gh_env():
    """Environment for gh CLI. Never prints or stores tokens."""
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    if GITHUB_CONFIG_DIR:
        env["GH_CONFIG_DIR"] = GITHUB_CONFIG_DIR
    return env


def _gh(args, timeout=30, check=True):
    if not shutil.which("gh"):
        raise RuntimeError("本机找不到 gh CLI，无法执行真实 GitHub PR/merge。")
    proc = subprocess.run(["gh"] + list(args), cwd=BASE_DIR, env=_gh_env(),
                          text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "gh command failed").strip()
        raise RuntimeError(redact(msg)[:800])
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def _github_login_check():
    if not shutil.which("gh"):
        return None, "本机找不到 gh CLI，无法执行真实 GitHub PR/merge。"
    try:
        login, _, _ = _gh(["api", "user", "--jq", ".login"], timeout=20)
    except Exception as e:
        return None, f"GitHub 登录态不可用或未授权：{e}"
    login = login.strip()
    if GITHUB_EXPECTED_LOGIN and login != GITHUB_EXPECTED_LOGIN:
        return None, f"当前 gh 登录账号是 {login}，不是预期的 {GITHUB_EXPECTED_LOGIN}；为避免用错账号，已拒绝。"
    return login, None


def _github_repo_slug():
    try:
        repo, _, _ = _gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], timeout=20)
        if repo.strip():
            return repo.strip(), None
    except Exception as e:
        return None, f"无法识别当前 GitHub 仓库：{e}"
    return None, "无法识别当前 GitHub 仓库。"


def _remote_default_branch():
    out, _, rc = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], timeout=10, check=False)
    if rc == 0 and out.strip().startswith("origin/"):
        return out.strip().split("/", 1)[1]
    for candidate in ("main", "master"):
        _, _, rc = _git(["rev-parse", "--verify", f"origin/{candidate}^{{commit}}"], timeout=10, check=False)
        if rc == 0:
            return candidate
    return "main"


def _safe_branch_name(raw, prefix="lingtai-simple/pr"):
    raw = (raw or "").strip()
    if not raw:
        raw = f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    raw = raw.replace("refs/heads/", "")
    raw = re.sub(r"[^0-9A-Za-z._/-]+", "-", raw).strip("/.-")
    raw = re.sub(r"/+", "/", raw)
    if not raw:
        raw = f"{prefix}-{uuid.uuid4().hex[:6]}"
    if raw in ("main", "master", "develop", "dev"):
        raw = f"{prefix}-{raw}-{uuid.uuid4().hex[:6]}"
    if raw.startswith("-") or raw.endswith("-"):
        raw = raw.strip("-") or f"{prefix}-{uuid.uuid4().hex[:6]}"
    return raw[:160]


def _sanitize_pr_title(text):
    title = redact((text or "").strip())
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        title = "Update LingTai Simple"
    if len(title) > 180:
        title = title[:177].rstrip() + "..."
    if _looks_like_secret(title):
        return None, "PR title 疑似包含 API key / token；请删除凭证后再发起。"
    return title, None


def _sanitize_pr_body(text):
    body = redact((text or "").strip())
    if _looks_like_secret(body):
        return None, "PR body 疑似包含 API key / token；请删除凭证后再发起。"
    if not body:
        body = "Created by Yuanjiang LingTai Simple after explicit confirmation."
    return _bounded(body, GITHUB_PR_BODY_MAX_CHARS), None


def _extract_pr_number(text):
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"(?:/pull/|#)(\d+)\b", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", text):
        return text
    return ""


def _sanitize_base_branch(base_branch):
    """Sanitize an existing base branch name without rewriting main/master."""
    base_branch = (base_branch or "main").strip().replace("refs/heads/", "")
    base_branch = re.sub(r"[^0-9A-Za-z._/-]+", "-", base_branch).strip("/.-")
    base_branch = re.sub(r"/+", "/", base_branch)
    return (base_branch or "main")[:160]


def _ensure_origin_base(base_branch):
    base_branch = _sanitize_base_branch(base_branch)
    _git(["fetch", "origin", base_branch], timeout=60, check=False)
    _, _, rc = _git(["rev-parse", "--verify", f"origin/{base_branch}^{{commit}}"], timeout=10, check=False)
    if rc != 0:
        return None, f"找不到远端 base 分支 origin/{base_branch}；请先推送或换一个 base_branch。"
    return base_branch, None



def _git_push_with_gh_auth(refspec, timeout=120):
    """Run git push using gh auth token through GIT_ASKPASS; never prints the token."""
    if not shutil.which("gh"):
        raise RuntimeError("本机找不到 gh CLI，无法通过 GitHub 登录态 push。")
    script = None
    try:
        fd, script = tempfile.mkstemp(prefix="lingtai-simple-gh-askpass-", text=True)
        gh_dir_line = f'export GH_CONFIG_DIR={json.dumps(GITHUB_CONFIG_DIR)}\n' if GITHUB_CONFIG_DIR else ""
        body = "#!/bin/sh\n" + gh_dir_line + "case \"$1\" in\n*Username*) echo x-access-token ;;&\n*Password*) gh auth token ;;&\n*) echo x-access-token ;;&\nesac\n"
        # POSIX sh does not support ;;& on macOS sh; write portable version instead.
        body = "#!/bin/sh\n" + gh_dir_line + "case \"$1\" in\n*Username*) echo x-access-token ;;\n*Password*) gh auth token ;;\n*) echo x-access-token ;;\nesac\n"
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(script, 0o700)
        env = {"GIT_ASKPASS": script, "GIT_USERNAME": "x-access-token"}
        if GITHUB_CONFIG_DIR:
            env["GH_CONFIG_DIR"] = GITHUB_CONFIG_DIR
        return _git(["push", "origin", refspec], timeout=timeout, extra_env=env)
    finally:
        if script:
            try:
                os.remove(script)
            except OSError:
                pass

def prepare_github_pr_approval(state, payload):
    """Queue a confirmation-gated real GitHub PR creation (L4)."""
    if not _git_available():
        return None, "当前目录不是 git 仓库，无法创建 GitHub PR。"
    login, err = _github_login_check()
    if err:
        return None, err
    repo, err = _github_repo_slug()
    if err:
        return None, err
    out, _, _ = _git(["status", "--porcelain"], timeout=10)
    if out.strip():
        return None, "工作区有未提交改动；请先用 L3 commit 或人工处理到干净状态，再创建 PR。"
    base_branch = (payload.get("base_branch") or _remote_default_branch()).strip()
    base_branch, err = _ensure_origin_base(base_branch)
    if err:
        return None, err
    head_commit, _, _ = _git(["rev-parse", "HEAD"], timeout=10)
    ahead, _, _ = _git(["rev-list", "--count", f"origin/{base_branch}..HEAD"], timeout=10, check=False)
    try:
        ahead_count = int((ahead or "0").strip())
    except ValueError:
        ahead_count = 0
    if ahead_count <= 0:
        return None, f"当前 HEAD 相对 origin/{base_branch} 没有新 commit；无法创建有内容的 PR。请先完成 L3 commit。"
    title, err = _sanitize_pr_title(payload.get("pr_title") or payload.get("title") or payload.get("description") or "Update LingTai Simple")
    if err:
        return None, err
    default_body = "\n".join([
        "## Summary",
        f"- Created by Yuanjiang LingTai Simple v0.9 after explicit confirmation.",
        f"- Base: `{base_branch}`",
        f"- Head commit: `{head_commit[:12]}`",
        "",
        "## Safety",
        "- Worktree was clean at preview time.",
        "- This action will push a branch and create a GitHub PR only; it will not merge.",
    ])
    body, err = _sanitize_pr_body(payload.get("pr_body") or default_body)
    if err:
        return None, err
    branch = _safe_branch_name(payload.get("branch_name") or payload.get("head_branch"), prefix="lingtai-simple/pr")
    if branch in (base_branch, "main", "master"):
        return None, "PR head branch 不能等于 base/main/master。"
    stat, _, _ = _git(["diff", "--stat", f"origin/{base_branch}..HEAD"], timeout=20, check=False)
    commits, _, _ = _git(["log", "--oneline", f"origin/{base_branch}..HEAD"], timeout=20, check=False)
    detail = "\n".join([
        f"GitHub repo：{repo}",
        f"GitHub login：{login}",
        f"base：{base_branch}",
        f"head branch：{branch}",
        f"head commit：{head_commit}",
        f"commits ahead：{ahead_count}",
        f"PR title：{title}",
        "边界：确认后会真实 git push 到 GitHub 并创建 PR；不会 merge。",
        "commits：",
        _bounded(commits, 1800),
        "diff stat：",
        _bounded(stat, 1800),
    ])
    ap = add_approval(state, {
        "action": "code_pr",
        "title": "Claude Code 苦力：允许开 PR（真实 GitHub PR）",
        "detail": detail,
        "preview": f"[GitHub PR 预览 / 确认后真实 push + create PR]\n{detail}",
        "github_repo": repo,
        "github_base_branch": base_branch,
        "github_head_branch": branch,
        "github_head_commit": head_commit,
        "github_pr_title": title,
        "github_pr_body": body,
    })
    log_event(state, f"真实 GitHub PR 已进入确认队列：{title}", kind="github")
    return {"queued_approval": ap["id"], "level": 4, "real_executor": True, "repo": repo, "base_branch": base_branch, "head_branch": branch, "head_commit": head_commit}, None


def github_pr_apply_real(state, ap):
    """Push a branch and create a real GitHub PR after explicit approval. Does not merge."""
    login, err = _github_login_check()
    if err:
        return None, err
    repo, err = _github_repo_slug()
    if err:
        return None, err
    if ap.get("github_repo") and ap.get("github_repo") != repo:
        return None, f"确认时仓库已变化：预览为 {ap.get('github_repo')}，当前为 {repo}；已拒绝。"
    out, _, _ = _git(["status", "--porcelain"], timeout=10)
    if out.strip():
        return None, "确认时工作区出现未提交改动；为避免把未审阅内容带入 PR，已拒绝。"
    head_commit, _, _ = _git(["rev-parse", "HEAD"], timeout=10)
    if ap.get("github_head_commit") and head_commit != ap.get("github_head_commit"):
        return None, "确认时 HEAD 与预览时不一致；请重新发起 L4 PR 请求。"
    base_branch = ap.get("github_base_branch") or _remote_default_branch()
    base_branch, err = _ensure_origin_base(base_branch)
    if err:
        return None, err
    branch = _safe_branch_name(ap.get("github_head_branch"), prefix="lingtai-simple/pr")
    if branch in (base_branch, "main", "master"):
        return None, "PR head branch 不安全，已拒绝。"
    ahead, _, _ = _git(["rev-list", "--count", f"origin/{base_branch}..HEAD"], timeout=10, check=False)
    if int((ahead or "0").strip() or "0") <= 0:
        return None, f"确认时 HEAD 相对 origin/{base_branch} 已无新 commit；已拒绝创建空 PR。"
    # Refuse overwriting an existing remote branch unless it already points to the same commit.
    remote_head, _, rc = _git(["ls-remote", "--heads", "origin", branch], timeout=20, check=False)
    if rc == 0 and remote_head.strip():
        remote_commit = remote_head.split()[0]
        if remote_commit != head_commit:
            return None, f"远端分支 origin/{branch} 已存在且不是当前 commit；为避免覆盖，已拒绝。"
    _git_push_with_gh_auth(f"HEAD:refs/heads/{branch}", timeout=120)
    title = ap.get("github_pr_title") or "Update LingTai Simple"
    body = ap.get("github_pr_body") or "Created by Yuanjiang LingTai Simple."
    out, _, _ = _gh(["pr", "create", "--repo", repo, "--base", base_branch, "--head", branch,
                     "--title", title, "--body", body], timeout=60)
    pr_url = out.strip().splitlines()[-1].strip() if out.strip() else ""
    pr_number = _extract_pr_number(pr_url)
    ap["github_pr_url"] = pr_url
    if pr_number:
        ap["github_pr_number"] = pr_number
    result = {
        "repo": repo,
        "login": login,
        "base_branch": base_branch,
        "head_branch": branch,
        "head_commit": head_commit,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "boundary": "created real GitHub PR only; not merged",
    }
    log_event(state, f"真实 GitHub PR 已创建：{pr_url or pr_number}", kind="github")
    return result, None


def prepare_github_merge_approval(state, payload):
    """Queue a confirmation-gated real GitHub PR merge (L5)."""
    login, err = _github_login_check()
    if err:
        return None, err
    repo, err = _github_repo_slug()
    if err:
        return None, err
    raw_pr = payload.get("pr_number") or payload.get("pr") or payload.get("pr_url") or payload.get("description") or ""
    pr_number = _extract_pr_number(str(raw_pr))
    if not pr_number:
        return None, "L5 merge 需要在 description/pr_number/pr_url 中写清楚 PR 编号或 URL，例如 `#12` 或 `/pull/12`。"
    try:
        info, _, _ = _gh(["pr", "view", pr_number, "--repo", repo,
                          "--json", "number,title,state,baseRefName,headRefName,url,mergeable,isDraft,author",
                          "--jq", "."], timeout=30)
        info_obj = json.loads(info)
    except Exception as e:
        return None, f"无法读取 PR #{pr_number}：{e}"
    if info_obj.get("state") != "OPEN":
        return None, f"PR #{pr_number} 当前状态不是 OPEN（{info_obj.get('state')}），不能进入 merge 确认队列。"
    if info_obj.get("isDraft"):
        return None, f"PR #{pr_number} 仍是 draft，不能 merge。"
    method = (payload.get("merge_method") or "merge").strip().lower()
    if method not in ("merge", "squash", "rebase"):
        return None, "merge_method 只能是 merge / squash / rebase。"
    detail = "\n".join([
        f"GitHub repo：{repo}",
        f"GitHub login：{login}",
        f"PR：#{info_obj.get('number')} {info_obj.get('title')}",
        f"URL：{info_obj.get('url')}",
        f"base：{info_obj.get('baseRefName')}",
        f"head：{info_obj.get('headRefName')}",
        f"mergeable：{info_obj.get('mergeable')}",
        f"method：{method}",
        "边界：确认后会真实执行 gh pr merge；这会改变远端 base 分支，不能用本地 rollback 撤回。",
    ])
    ap = add_approval(state, {
        "action": "code_merge",
        "title": f"Claude Code 苦力：允许 merge PR #{pr_number}（真实 GitHub merge）",
        "detail": detail,
        "preview": f"[GitHub merge 预览 / 确认后真实合并]\n{detail}",
        "github_repo": repo,
        "github_pr_number": str(pr_number),
        "github_pr_url": info_obj.get("url") or "",
        "github_base_branch": info_obj.get("baseRefName") or "",
        "github_head_branch": info_obj.get("headRefName") or "",
        "github_merge_method": method,
    })
    log_event(state, f"真实 GitHub merge 已进入确认队列：PR #{pr_number}", kind="github")
    return {"queued_approval": ap["id"], "level": 5, "real_executor": True, "repo": repo, "pr_number": str(pr_number), "pr_url": info_obj.get("url")}, None


def github_merge_apply_real(state, ap):
    """Merge a real GitHub PR after explicit approval."""
    login, err = _github_login_check()
    if err:
        return None, err
    repo, err = _github_repo_slug()
    if err:
        return None, err
    if ap.get("github_repo") and ap.get("github_repo") != repo:
        return None, f"确认时仓库已变化：预览为 {ap.get('github_repo')}，当前为 {repo}；已拒绝。"
    pr_number = _extract_pr_number(ap.get("github_pr_number") or ap.get("github_pr_url") or "")
    if not pr_number:
        return None, "确认项缺少 PR 编号；已拒绝 merge。"
    try:
        info, _, _ = _gh(["pr", "view", pr_number, "--repo", repo,
                          "--json", "number,title,state,baseRefName,headRefName,url,mergeable,isDraft",
                          "--jq", "."], timeout=30)
        info_obj = json.loads(info)
    except Exception as e:
        return None, f"确认时无法读取 PR #{pr_number}：{e}"
    if info_obj.get("state") != "OPEN":
        return None, f"确认时 PR #{pr_number} 状态不是 OPEN（{info_obj.get('state')}），已拒绝。"
    if info_obj.get("isDraft"):
        return None, f"确认时 PR #{pr_number} 仍是 draft，已拒绝。"
    if ap.get("github_base_branch") and info_obj.get("baseRefName") != ap.get("github_base_branch"):
        return None, "确认时 PR base 分支已变化；请重新发起 L5 merge 请求。"
    if ap.get("github_head_branch") and info_obj.get("headRefName") != ap.get("github_head_branch"):
        return None, "确认时 PR head 分支已变化；请重新发起 L5 merge 请求。"
    method = (ap.get("github_merge_method") or "merge").strip().lower()
    flag = {"merge": "--merge", "squash": "--squash", "rebase": "--rebase"}.get(method, "--merge")
    out, _, _ = _gh(["pr", "merge", pr_number, "--repo", repo, flag, "--delete-branch"], timeout=120)
    result = {
        "repo": repo,
        "login": login,
        "pr_number": str(pr_number),
        "pr_url": info_obj.get("url") or ap.get("github_pr_url") or "",
        "base_branch": info_obj.get("baseRefName"),
        "head_branch": info_obj.get("headRefName"),
        "merge_method": method,
        "gh_output": _bounded(redact(out), 2000),
        "boundary": "merged real GitHub PR; external side effect cannot be undone by local rollback",
    }
    log_event(state, f"真实 GitHub PR 已 merge：#{pr_number}", kind="github")
    return result, None

def prepare_cc_readonly_run(state, payload):
    desc = (payload.get("description") or "").strip()
    if not desc:
        return None, None, "请先写清楚要让 Claude Code 只读分析什么。"
    if _looks_like_secret(desc):
        return None, None, "任务描述里像是包含 API key / token。为安全起见，不会发送给外部 Claude Code。请删除凭证后再提交。"
    if not payload.get("confirm_cost"):
        return None, None, "真实 Claude Code 只读分析会调用外部模型，可能产生费用；请勾选费用确认后再执行。"
    if not claude_code_available():
        return None, None, "本机找不到 claude CLI，无法真实执行 Claude Code worker。"
    run = {
        "id": new_id("ccrun"),
        "level": 1,
        "label": "只读分析",
        "description": redact(desc),
        "status": "运行中",
        "created_at": now_iso(),
        "started_at": now_iso(),
        "finished_at": None,
        "exit_code": None,
        "duration_ms": None,
        "output_preview": "",
        "report_path": "",
        "safety_note": "只读分析：仅允许 Claude Code 使用 Read/Grep/Glob；不允许 Edit/Write/Bash；不会 commit/PR/merge。",
    }
    state.setdefault("cc_runs", []).insert(0, run)
    state["cc_runs"] = state["cc_runs"][:30]
    log_event(state, f"Claude Code 只读分析开始：{desc[:60]}", kind="claude_code")
    return run, desc, None


def run_claude_code_readonly(run, desc):
    """锁外执行真实 Claude Code 只读分析；返回更新字段，不修改 state。"""
    os.makedirs(CC_RUN_DIR, exist_ok=True)
    started = time.time()
    prompt = (
        "你是 LingTai Simple 的受控 Claude Code 只读分析 worker。\n"
        "硬性规则：只做阅读、搜索、分析和建议；不要修改文件；不要执行 shell；不要提交、开 PR 或 merge；"
        "不要输出任何凭证或秘密。若看到疑似秘密，只写 [REDACTED]。\n\n"
        f"工作目录：{BASE_DIR}\n"
        f"任务：{desc}\n\n"
        "请用中文输出：1) 结论摘要；2) 关键证据/文件；3) 建议下一步；4) 风险与边界。"
    )
    cmd = [
        shutil.which("claude") or "claude",
        "--print",
        "--permission-mode", "plan",
        "--allowedTools", "Read,Grep,Glob",
        "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
        "--max-budget-usd", str(CC_MAX_BUDGET_USD),
        "--no-session-persistence",
        "--add-dir", BASE_DIR,
        prompt,
    ]
    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_SIMPLE", "1")
    try:
        proc = subprocess.run(cmd, cwd=BASE_DIR, env=env, capture_output=True, text=True,
                              timeout=CC_RUN_TIMEOUT)
        stdout = redact(proc.stdout or "")
        stderr = redact(proc.stderr or "")
        status = "完成" if proc.returncode == 0 else "失败"
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = redact(e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = redact(e.stderr or "") if isinstance(e.stderr, str) else ""
        stderr = (stderr + f"\nTIMEOUT after {CC_RUN_TIMEOUT}s").strip()
        status = "超时"
        exit_code = 124
    duration_ms = int((time.time() - started) * 1000)
    combined = (stdout.strip() + ("\n\n[stderr]\n" + stderr.strip() if stderr.strip() else "")).strip()
    if not combined:
        combined = "（Claude Code 没有返回可显示内容。）"
    report_path = os.path.join(CC_RUN_DIR, f"{run['id']}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Claude Code 只读分析报告\n\n")
        f.write(f"- run_id: `{run['id']}`\n- status: {status}\n- exit_code: {exit_code}\n")
        f.write(f"- duration_ms: {duration_ms}\n- created_at: {run.get('created_at')}\n")
        f.write(f"- safety: Read/Grep/Glob only; no Bash/Edit/Write; no commit/PR/merge.\n\n")
        f.write("## Task\n\n")
        f.write(redact(desc) + "\n\n")
        f.write("## Output\n\n")
        f.write(combined + "\n")
    return {
        "status": status,
        "finished_at": now_iso(),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "output_preview": _bounded(combined, CC_MAX_OUTPUT_CHARS),
        "report_path": report_path,
        "command_summary": "claude --print --permission-mode plan --allowedTools Read,Grep,Glob --disallowedTools Bash,Edit,Write,...",
    }


def _worktree_clean():
    if not _git_available():
        return False, "当前目录不是 git 仓库，无法安全应用 Claude Code 本地改码。"
    out, _, _ = _git(["status", "--porcelain"], timeout=10)
    if out.strip():
        return False, "仓库当前已有未提交改动；为避免覆盖，请先快照/提交/回滚到干净状态后再运行 L2 本地改码。"
    return True, None


def _changed_files_from_diff(diff_text):
    files = []
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                name = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                files.append(name)
    return files[:80]


def _high_confidence_secret_hits(root_dir, paths=None):
    """Small local high-confidence scan; never prints matched secrets, only file + pattern name.

    If paths is provided, scan only changed files. Known fake/self-check markers are ignored.
    """
    patterns = [
        ("OPENAI_OR_SK", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
        ("GITHUB_PAT", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
        ("GITHUB_FINE_GRAINED_PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
        ("TELEGRAM_BOT_TOKEN", re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}\b")),
        ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9_\-.]{24,}\b", re.IGNORECASE)),
    ]
    fake_markers = ("FAKE", "NOT-A-REAL", "SELF_CHECK", "selfcheck")
    skip_dirs = {".git", "__pycache__", "data", "node_modules", ".venv", "venv"}
    hits = []
    if paths:
        candidates = [os.path.join(root_dir, p) for p in paths if p and not p.startswith("data/")]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                candidates.append(os.path.join(dirpath, fn))
    for path in candidates:
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > 2_000_000:
                continue
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        rel = os.path.relpath(path, root_dir)
        for line in lines:
            if any(marker in line for marker in fake_markers):
                continue
            for name, pat in patterns:
                if pat.search(line):
                    hits.append({"file": rel, "pattern": name})
                    break
            if hits and hits[-1].get("file") == rel:
                break
    return hits[:50]


def _run_py_compile_check(root_dir):
    candidates = []
    for rel in ("server.py", "scripts/self_check.py", "scripts/load_demo.py"):
        if os.path.exists(os.path.join(root_dir, rel)):
            candidates.append(rel)
    if not candidates:
        return {"ok": True, "output": "No Python entry files found."}
    proc = subprocess.run(["python3", "-m", "py_compile"] + candidates, cwd=root_dir,
                          text=True, capture_output=True, timeout=60)
    return {"ok": proc.returncode == 0, "output": redact((proc.stdout + proc.stderr).strip())[:2000]}


def prepare_cc_local_edit_run(state, payload):
    desc = (payload.get("description") or "").strip()
    if not desc:
        return None, None, "请先写清楚要让 Claude Code 本地修改什么。"
    if _looks_like_secret(desc):
        return None, None, "任务描述里像是包含 API key / token。为安全起见，不会发送给外部 Claude Code。请删除凭证后再提交。"
    if not payload.get("confirm_cost"):
        return None, None, "真实 Claude Code L2 本地改码会调用外部模型、可能产生费用并修改本仓库文件；请勾选费用/本地改动确认后再执行。"
    if not claude_code_available():
        return None, None, "本机找不到 claude CLI，无法真实执行 Claude Code worker。"
    clean, err = _worktree_clean()
    if not clean:
        return None, None, err
    run = {
        "id": new_id("ccrun"),
        "level": 2,
        "label": "本地改码（不提交）",
        "description": redact(desc),
        "status": "运行中",
        "created_at": now_iso(),
        "started_at": now_iso(),
        "finished_at": None,
        "exit_code": None,
        "duration_ms": None,
        "output_preview": "",
        "report_path": "",
        "changed_files": [],
        "patch_applied": False,
        "safety_ref": "",
        "safety_note": "L2 本地改码：在隔离 git worktree 中允许 Edit/Write；禁止 Bash/Web；通过 py_compile 与高置信秘密扫描后才把 patch 应用回本仓库；不 commit/PR/merge。",
    }
    state.setdefault("cc_runs", []).insert(0, run)
    state["cc_runs"] = state["cc_runs"][:30]
    log_event(state, f"Claude Code L2 本地改码开始：{desc[:60]}", kind="claude_code")
    return run, desc, None


def run_claude_code_local_edit(run, desc):
    """Run Claude Code in an isolated git worktree, validate, then apply a patch to BASE_DIR."""
    os.makedirs(CC_RUN_DIR, exist_ok=True)
    os.makedirs(CC_WORKTREE_DIR, exist_ok=True)
    started = time.time()
    report_path = os.path.join(CC_RUN_DIR, f"{run['id']}.md")
    worktree = os.path.join(CC_WORKTREE_DIR, run["id"])
    status = "失败"
    exit_code = 1
    combined = ""
    diff_text = ""
    changed_files = []
    checks = {}
    safety = None
    try:
        safety = _create_tree_commit_ref(SAFETY_REF_PREFIX, f"before-cc-l2-{run['id']}")
        _git(["worktree", "add", "--detach", worktree, "HEAD"], timeout=30)
        prompt = (
            "你是 LingTai Simple 的受控 Claude Code L2 本地改码 worker。\n"
            "硬性规则：可以在当前隔离 worktree 内修改文件；不要执行 shell；不要访问网络；不要提交、开 PR 或 merge；"
            "不要写入或输出任何凭证。若看到疑似秘密，只写 [REDACTED]。\n"
            "修改要小而可审计，优先完成用户指定任务；完成后用中文摘要说明改了哪些文件、为何修改、如何验证。\n\n"
            f"隔离工作目录：{worktree}\n"
            f"任务：{desc}\n"
        )
        cmd = [
            shutil.which("claude") or "claude",
            "--print",
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Grep,Glob,Edit,Write",
            "--disallowedTools", "Bash,NotebookEdit,WebFetch,WebSearch",
            "--max-budget-usd", str(CC_MAX_BUDGET_USD),
            "--no-session-persistence",
            "--add-dir", worktree,
            prompt,
        ]
        env = os.environ.copy()
        env.setdefault("CLAUDE_CODE_SIMPLE", "1")
        proc = subprocess.run(cmd, cwd=worktree, env=env, capture_output=True, text=True,
                              timeout=CC_RUN_TIMEOUT)
        stdout = redact(proc.stdout or "")
        stderr = redact(proc.stderr or "")
        exit_code = proc.returncode
        combined = (stdout.strip() + ("\n\n[stderr]\n" + stderr.strip() if stderr.strip() else "")).strip()
        if exit_code != 0:
            status = "失败"
        else:
            # include untracked files in the patch
            subprocess.run(["git", "add", "-N", "--", "."], cwd=worktree, text=True,
                           capture_output=True, timeout=20)
            dproc = subprocess.run(["git", "diff", "--binary", "--", "."], cwd=worktree,
                                   text=True, capture_output=True, timeout=30)
            raw_diff = dproc.stdout or ""
            diff_text = raw_diff
            changed_files = _changed_files_from_diff(raw_diff)
            if not raw_diff.strip():
                status = "无改动"
            elif len(raw_diff) > 240_000:
                status = "失败"
                combined += "\n\n[guard] diff 过大，已拒绝自动应用。"
            else:
                checks["py_compile"] = _run_py_compile_check(worktree)
                checks["secret_hits"] = _high_confidence_secret_hits(worktree, changed_files)
                if not checks["py_compile"].get("ok"):
                    status = "校验失败"
                    combined += "\n\n[guard] py_compile 未通过，patch 未应用。"
                elif checks["secret_hits"]:
                    status = "校验失败"
                    combined += "\n\n[guard] 高置信秘密扫描发现疑似凭证，patch 未应用。"
                else:
                    apply_proc = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"],
                                                cwd=BASE_DIR, input=raw_diff, text=True,
                                                capture_output=True, timeout=30)
                    if apply_proc.returncode != 0:
                        status = "应用失败"
                        combined += "\n\n[git apply]\n" + redact((apply_proc.stdout + apply_proc.stderr).strip())
                    else:
                        status = "完成"
        if not combined:
            combined = "（Claude Code 没有返回可显示内容。）"
    except subprocess.TimeoutExpired as e:
        status = "超时"
        exit_code = 124
        combined = redact((e.stdout or "") if isinstance(e.stdout, str) else "")
        combined += f"\nTIMEOUT after {CC_RUN_TIMEOUT}s"
    except Exception as e:
        status = "失败"
        combined = redact(str(e))
    finally:
        try:
            _git(["worktree", "remove", "--force", worktree], timeout=30, check=False)
        except Exception:
            pass
    duration_ms = int((time.time() - started) * 1000)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Claude Code L2 本地改码报告\n\n")
        f.write(f"- run_id: `{run['id']}`\n- status: {status}\n- exit_code: {exit_code}\n")
        f.write(f"- duration_ms: {duration_ms}\n- created_at: {run.get('created_at')}\n")
        f.write(f"- safety_ref: `{safety.get('ref') if safety else ''}`\n")
        f.write("- safety: isolated git worktree; Bash/Web disabled; py_compile + high-confidence secret scan before applying patch; no commit/PR/merge.\n\n")
        f.write("## Task\n\n" + redact(desc) + "\n\n")
        f.write("## Changed files\n\n")
        if changed_files:
            for name in changed_files:
                f.write(f"- `{name}`\n")
        else:
            f.write("- （无）\n")
        f.write("\n## Checks\n\n```json\n" + json.dumps(checks, ensure_ascii=False, indent=2) + "\n```\n\n")
        f.write("## Claude output\n\n" + combined + "\n\n")
        if diff_text:
            f.write("## Diff preview\n\n```diff\n" + _bounded(redact(diff_text), 20000) + "\n```\n")
    return {
        "status": status,
        "finished_at": now_iso(),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "output_preview": _bounded(combined, CC_MAX_OUTPUT_CHARS),
        "report_path": report_path,
        "changed_files": changed_files,
        "diff_preview": _bounded(redact(diff_text), 6000),
        "patch_applied": status == "完成",
        "safety_ref": safety.get("ref") if safety else "",
        "checks": checks,
    }


def request_cc_task(state, payload):
    """Claude Code 苦力卡：v0.9 真实接入 L1/L2/L3/L4/L5；所有高危动作走确认闸。"""
    level = parse_level(payload.get("level"), 1)
    if level == 1:
        return None, "Claude Code L1 只读分析已是 真实外部调用；请通过专用处理器并勾选费用确认。"
    if level == 2:
        return None, "Claude Code L2 本地改码已是真实外部调用并会修改本仓库文件；请通过专用处理器并勾选费用/本地改动确认。"
    if level == 3:
        return prepare_cc_commit_approval(state, payload)
    if level == 4:
        return prepare_github_pr_approval(state, payload)
    if level == 5:
        return prepare_github_merge_approval(state, payload)
    return prepare_github_pr_approval(state, payload)

def load_demo_state(_state=None, _payload=None):
    """把 data/state.example.json 载入运行态，方便圆酱打开就看见完整效果。"""
    try:
        with open(EXAMPLE_STATE_PATH, "r", encoding="utf-8") as f:
            demo = json.load(f)
    except OSError:
        demo = default_state()
    demo["meta"]["name"] = "圆酱专属轻量版灵台 / LingTai Simple v0.9（示例模式）"
    demo["meta"]["loaded_demo_at"] = now_iso()
    demo.setdefault("log", [])
    log_event(demo, "加载示例数据：圆酱专属灵台 v0.8 demo")
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
        "git_available": _git_available(),
        "claude_code_available": claude_code_available(),
        "github_cli_available": shutil.which("gh") is not None,
    }
    return {
        "ok": all(checks.values()),
        "version": "v0.9",
        "host": HOST,
        "port": PORT,
        "checks": checks,
        "keychain_available": keychain_available(),
        "boundaries": [
            "localhost-only",
            "real model API calls require explicit UI action (may cost money)",
            "real git Time Machine / rollback: snapshot, diff preview, confirmation-gated reset --hard",
            "real WeChat command entry via current LingTai WeChat MCP bridge; no second WeChat poller is started",
            "real Claude Code L1 read-only analysis worker (explicit cost confirmation required)",
            "real Claude Code L2 local-edit worker: isolated worktree, validation, patch apply to this repo",
            "real Claude Code L3 commit executor: confirmation-gated local git commit only",
            "real Claude Code L4 PR executor: confirmation-gated branch push + GitHub PR creation",
            "real Claude Code L5 merge executor: confirmation-gated GitHub PR merge",
            "not connected yet: autonomous standalone WeChat poller",
            "no plaintext API key in JSON/logs/responses (Keychain-only)",
        ],
    }


# --------------------------------------------------------------------------
# HTTP Handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LingTaiSimple/0.9"

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
                "keychain_available": keychain_available(),
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

        # 真实模型调用单独处理：网络请求（最长 30s）在锁外进行，避免阻塞 UI 轮询。
        if route == "/api/model/test":
            return self._handle_model_test(payload)
        if route == "/api/cc/request":
            return self._handle_cc_request(payload)

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

    def _handle_model_test(self, payload):
        """真实模型调用：锁内取 key/配置 → 锁外发请求 → 锁内记日志并存盘。"""
        with _LOCK:
            state = load_state()
            spec, err = prepare_model_test(state, payload)
            if err:
                return self._send_json({"ok": False, "error": err}, 400)
            save_state(state)  # 已记录「发起调用」日志

        # 锁外：发起真实网络请求（可能耗时 / 可能计费）。spec 含明文 key，仅本地内存。
        result, err = real_model_call(
            spec["base_url"], spec["model"], spec["api_key"], spec["prompt"])
        spec["api_key"] = None  # 立即丢弃 key 引用

        with _LOCK:
            state = load_state()
            pid = spec["provider_id"]
            if err:
                log_event(state, f"真实模型调用失败：{pid}（{err[:80]}）", kind="real_api")
                save_state(state)
                resp = {"ok": False, "error": err, "state": self._public_state(state)}
                return self._send_json(resp, 400)
            result.pop("api_key", None)  # 防御性
            log_event(state, f"真实模型调用成功：{pid} / {result.get('model')} "
                             f"（{result.get('latency_ms')}ms）", kind="real_api")
            save_state(state)
            return self._send_json({"ok": True, "result": result,
                                    "state": self._public_state(state)})

    def _handle_cc_request(self, payload):
        """真实 Claude Code worker：L1 只读分析；L2 本地改码；L3 本地 commit；L4/L5 仍只进确认队列。"""
        level = parse_level(payload.get("level"), 1)
        if level not in (1, 2):
            with _LOCK:
                state = load_state()
                result, err = request_cc_task(state, payload)
                if err:
                    return self._send_json({"ok": False, "error": err}, 400)
                save_state(state)
                return self._send_json({"ok": True, "result": result, "state": self._public_state(state)})

        with _LOCK:
            state = load_state()
            if level == 1:
                run, desc, err = prepare_cc_readonly_run(state, payload)
            else:
                run, desc, err = prepare_cc_local_edit_run(state, payload)
            if err:
                return self._send_json({"ok": False, "error": err}, 400)
            save_state(state)

        update = run_claude_code_readonly(run, desc) if level == 1 else run_claude_code_local_edit(run, desc)

        with _LOCK:
            state = load_state()
            runs = state.setdefault("cc_runs", [])
            target = next((r for r in runs if r.get("id") == run["id"]), None)
            if target is None:
                target = run
                runs.insert(0, target)
            target.update(update)
            label = "只读分析" if level == 1 else "L2 本地改码"
            log_event(state, f"Claude Code {label}{update['status']}：{run['id']}（{update['duration_ms']}ms）", kind="claude_code")
            save_state(state)
            ok = update["status"] in ("完成", "无改动")
            resp = {"ok": ok, "result": target, "state": self._public_state(state)}
            return self._send_json(resp, 200 if ok else 400)

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
            "/api/provider/delete_key": lambda s, p: delete_provider_key(s, p),
            "/api/provider/check_key": lambda s, p: check_provider_key(s, p),
            "/api/wechat/submit": lambda s, p: wechat_submit(s, p),
            "/api/wechat/bridge/incoming": lambda s, p: wechat_bridge_incoming(s, p),
            "/api/wechat/bridge/mark_sent": lambda s, p: wechat_bridge_mark_sent(s, p),
            "/api/demo/load": lambda s, p: load_demo_state(s, p),
            "/api/shougong": lambda s, p: (generate_shougong(s), None),
            "/api/rollback/snapshot": lambda s, p: create_snapshot(s, p),
            "/api/rollback/request": lambda s, p: request_rollback(s, p.get("snapshot_id")),
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
            "wechat_inbox": state.get("wechat_inbox", [])[:30],
            "wechat_outbox": state.get("wechat_outbox", [])[:30],
            "wechat_bridge": state.get("wechat_bridge", {}),
            "cc_runs": state.get("cc_runs", [])[:20],
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
    """写出 state.example.json（示例数据，供参考）。

    示例文件是 tracked 文档资产，不能每次启动都因动态时间戳变脏，
    否则 L3 commit 预览会把运行服务产生的无关改动纳入候选。
    """
    example = default_state()
    example["meta"]["created_at"] = DEMO_TIMESTAMP
    a1 = {
        "id": "agent_demo0001", "name": "营养审稿灵", "role": "长期助手",
        "provider_id": "deepseek", "model": "deepseek-chat", "cc_level": 1,
        "status": "待命", "created_at": DEMO_TIMESTAMP, "recent_tasks": [], "context_base": 18,
    }
    a1["context_pressure"] = estimate_context_pressure(a1)
    a2 = {
        "id": "agent_demo0002", "name": "代码管家灵", "role": "代码苦力",
        "provider_id": "openai", "model": "gpt-4o", "cc_level": 2,
        "status": "正在干", "created_at": DEMO_TIMESTAMP,
        "recent_tasks": ["task_demoaaaa"], "context_base": 30,
    }
    a2["context_pressure"] = estimate_context_pressure(a2)
    example["agents"] = [a1, a2]
    example["providers"] = [{
        "provider_id": "deepseek", "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
        "tags": ["chat", "code", "cheap"], "configured": True, "in_keychain": True,
        "key_label": "圆酱-DS", "key_last4": "1234", "updated_at": DEMO_TIMESTAMP,
    }]
    example["wechat_inbox"] = [{
        "id": "wx_demo0001", "text": "让代码苦力看一下这个仓库，给我改个 README，但不要直接提交。",
        "received_at": DEMO_TIMESTAMP, "ack": "已收到 ✅（mock）",
        "stages": ["已收到", "排队中", "执行中", "等确认（敏感动作）"],
        "status": "等确认", "assignee": "代码管家灵",
        "result": "涉及改码，已进入确认队列。",
    }]
    rendered = json.dumps(example, ensure_ascii=False, indent=2) + "\n"
    try:
        with open(EXAMPLE_STATE_PATH, "r", encoding="utf-8") as f:
            if f.read() == rendered:
                return
    except OSError:
        pass
    with open(EXAMPLE_STATE_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CC_RUN_DIR, exist_ok=True)
    ensure_example_state()
    load_state()  # 确保 state.json 存在
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=" * 64)
    print("  圆酱专属轻量版灵台 / LingTai Simple v0.9 — 本地原型")
    print("=" * 64)
    print(f"  地址 : http://{HOST}:{PORT}/")
    print(f"  状态 : {STATE_PATH}")
    print("  边界 : localhost-only / Keychain + 模型 API + git Time Machine + 微信桥接 + Claude Code L1/L2/L3 为真实能力 / PR-merge 尚未接入")
    print("  停止 : Ctrl+C")
    print("=" * 64)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.server_close()


if __name__ == "__main__":
    main()
