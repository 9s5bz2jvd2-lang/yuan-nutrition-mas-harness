#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
圆酱专属轻量版灵台 / LingTai Simple v0.21 — 本地原型服务器

边界（硬红线）：
- 默认 localhost-only（绑定 127.0.0.1）。
- v0.21 已真实接入：Keychain 密钥保险柜、OpenAI-compatible 模型 API 调用、git Time Machine / rollback、微信桥接入口、Claude Code L1-L5 执行闸、多 agent/洞察/心流、LingTai 内部邮箱派发、真实 agent 回复回收、受控 worker 调度请求与回信汇总，以及确认后的 lifecycle signal / CPR。
- 微信桥接不启动第二个 poller、不保存微信凭证；真实收发仍由当前 LingTai WeChat MCP 作为唯一桥接者完成。
- Claude Code L1 只读分析与 L2 本地改码已真实接入（需显式确认可能产生费用；L2 会修改本仓库文件）；commit、PR、merge 均已接入确认闸；L4 会真实 push 分支并创建 GitHub PR，L5 会在确认后真实合并指定 PR。
- 不保存明文 API key 到 JSON / 日志 / API 响应；明文 key 只存进 Mac Keychain。

v0.21 的「真实能力」（与 v0.2 的纯 mock 不同）：
- 通过 macOS Security.framework 把 API key 存进系统 Keychain（fallback：清晰报错，绝不落明文）。
- 对 OpenAI-compatible /chat/completions 端点发起**真实**网络请求（需用户在 UI 显式点击，
  并明确标注「可能产生费用」）。
- git Time Machine：创建安全快照、列快照、预览 diff，并在确认队列批准后执行真实 `git reset --hard` 回退。
- 微信桥接入口：当前 LingTai/WeChat MCP 可把真实微信消息 POST 到本服务，本服务写入任务/确认队列并返回可原路回复的 `reply_text`。
- Claude Code worker：L1 显式确认费用后调用本机 `claude --print` 做只读分析；L2 在隔离 git worktree 中允许本地改码，经 py_compile 与高置信秘密扫描后把 patch 应用回本仓库；L3 可在再次确认后创建真实本地 git commit；L4 可在确认后 push 分支并创建 GitHub PR；L5 可在确认后 merge 指定 PR。
- LingTai runtime 桥：可写真实内部邮箱 outbox 派发任务，可只读回收 reply_inbox 中匹配的真实 agent 回信；lull/suspend/interrupt/clear/CPR 先入确认队列，批准后才写 signal 或尝试复苏。

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
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import tempfile
import time
from pathlib import Path

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
    "lingtai_lifecycle", "lingtai_avatar_spawn", "lingtai_avatar_retire",
    "worker_dispatch",
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

# 受限 Secret fallback：Keychain 不可用/被锁定时，用户可显式选择把 key 存入
# .secrets/providers/<provider>.key。该目录/文件必须是 0700/0600；健康检查只看权限和
# 位置，绝不回显内容。env slot 作为只读 fallback：LINGTAI_SIMPLE_API_KEY_<PROVIDER_ID>。
SECRETS_DIR = Path(BASE_DIR) / ".secrets"
SECRET_PROVIDER_DIR = SECRETS_DIR / "providers"
SECRET_FALLBACK_ENV_PREFIX = "LINGTAI_SIMPLE_API_KEY_"
KEYCHAIN_DISABLED = os.environ.get("LINGTAI_SIMPLE_DISABLE_KEYCHAIN", "").strip().lower() in ("1", "true", "yes", "on")

# 真实模型调用的安全上限（避免误操作烧钱）。
MODEL_CALL_TIMEOUT = 30          # 秒
MODEL_CALL_MAX_TOKENS = 256      # 单次测试回复上限

# 累计预算 / 成本面板（v0.21）：所有金额均是本地估算值，不连接供应商账单。
# 单位：USD。价格表只用于“先拦截、先提醒”的保守估算；用户可在后续版本改成自己的真实价格表。
DEFAULT_DAILY_COST_CAP_USD = 1.00
DEFAULT_PROVIDER_CALL_CAP_USD = 0.05
DEFAULT_TASK_COST_CAP_USD = 0.25
DEFAULT_CC_RUN_CAP_USD = 0.50
DEFAULT_LONG_RUN_SECONDS = 15 * 60
DEFAULT_PROVIDER_PRICE_PER_1M = {
    "openai": {"input": 5.00, "output": 15.00, "note": "默认保守估算；请按实际模型价格调整。"},
    "deepseek": {"input": 0.55, "output": 2.19, "note": "默认估算；不同模型/缓存价格不同。"},
    "glm": {"input": 0.30, "output": 0.30, "note": "默认低价估算；不同 GLM 模型价格不同。"},
    "mimo": {"input": 1.00, "output": 1.00, "note": "未知供应商价格，占位估算。"},
    "minimax": {"input": 1.00, "output": 1.00, "note": "未知供应商价格，占位估算。"},
    "custom": {"input": 1.00, "output": 1.00, "note": "自定义供应商占位估算。"},
}

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


def _detect_lingtai_network_dir():
    """Find the surrounding `.lingtai` network without hard-coding this repo path."""
    cur = Path(BASE_DIR).resolve()
    for parent in [cur] + list(cur.parents):
        if parent.name == ".lingtai" and parent.is_dir():
            return str(parent)
        cand = parent / ".lingtai"
        if cand.is_dir():
            return str(cand)
    return ""


def _detect_lingtai_agent_dir():
    """Find the current real LingTai agent directory for read-only memory/skill views."""
    cur = Path(BASE_DIR).resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / ".agent.json").is_file() and (parent / "system").is_dir():
            return str(parent)
    return ""


LINGTAI_NETWORK_DIR = os.environ.get("LINGTAI_SIMPLE_NETWORK_DIR") or _detect_lingtai_network_dir()
LINGTAI_AGENT_DIR = os.environ.get("LINGTAI_SIMPLE_AGENT_DIR") or _detect_lingtai_agent_dir()
LINGTAI_MAIL_SENDER = os.environ.get("LINGTAI_SIMPLE_MAIL_SENDER", "human")
LINGTAI_REPLY_INBOX = os.environ.get("LINGTAI_SIMPLE_REPLY_INBOX", "mimo-2-5-pro")
LINGTAI_WORKER_CONTROLLER = os.environ.get("LINGTAI_SIMPLE_WORKER_CONTROLLER", LINGTAI_REPLY_INBOX)
LINGTAI_AGENT_CMD = os.environ.get("LINGTAI_SIMPLE_AGENT_CMD", os.path.expanduser("~/.lingtai-tui/runtime/venv/bin/lingtai-agent"))
LINGTAI_HEARTBEAT_FRESH_SECONDS = int(os.environ.get("LINGTAI_SIMPLE_HEARTBEAT_FRESH_SECONDS", "90"))


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


_SECRET_FIELD_RE = re.compile(r"(^|[_\-])(api[_\-]?key|token|secret|password|bearer|authorization)($|[_\-])", re.IGNORECASE)
_SAFE_SECRET_FIELD_RE = re.compile(r"(keychain|key_last4|last4|key_label|label|configured|in_keychain)", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|Bearer\s+[A-Za-z0-9_\-\.]{12,}|[A-Za-z0-9_\-]{32,})",
    re.IGNORECASE,
)
_SECRET_PLACEHOLDER_RE = re.compile(r"(fake|dummy|example|placeholder|not[_-]?real|redacted|xxxx|\*\*\*)", re.IGNORECASE)


def _is_sensitive_field(name):
    name = str(name or "")
    return bool(_SECRET_FIELD_RE.search(name)) and not _SAFE_SECRET_FIELD_RE.search(name)


def _looks_plain_secret(value, *, field_sensitive=False):
    """High-confidence plaintext secret heuristic; never returns or logs the value."""
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw or _SECRET_PLACEHOLDER_RE.search(raw):
        return False
    if _SECRET_VALUE_RE.search(raw):
        return True
    return bool(field_sensitive and len(raw) >= 12)


def _scan_json_secret_fields(obj, path=""):
    risks = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            field_path = f"{path}.{key}" if path else str(key)
            sensitive = _is_sensitive_field(key)
            if isinstance(value, (dict, list)):
                risks.extend(_scan_json_secret_fields(value, field_path))
            elif _looks_plain_secret(value, field_sensitive=sensitive):
                risks.append({
                    "severity": "high" if sensitive else "medium",
                    "kind": "json_sensitive_field" if sensitive else "secret_like_value",
                    "field_path": field_path,
                    "action": "把明文值移入 Mac Keychain 或受限 env/.secrets；state/示例/日志中只保留 last4/label/in_keychain。",
                })
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            risks.extend(_scan_json_secret_fields(value, f"{path}[{idx}]"))
    return risks


def _scan_text_secret_lines(text):
    risks = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if _SECRET_PLACEHOLDER_RE.search(line):
            continue
        # Assignment-style secret fields are high confidence; arbitrary long tokens are medium.
        if re.search(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*['\"]?[^'\"\s]{12,}", line):
            risks.append({"severity": "high", "kind": "text_secret_assignment", "line": lineno,
                          "action": "删除此明文配置，改存 Keychain；提交/汇报前重新跑健康检查。"})
        elif _SECRET_VALUE_RE.search(line):
            risks.append({"severity": "medium", "kind": "secret_like_text", "line": lineno,
                          "action": "核对此长串是否为凭证；若是，移入 Keychain/受限 env 并从文件删除。"})
    return risks[:20]


def secret_vault_health_scan():
    """Read-only plaintext secret risk scan. Values are never returned."""
    candidates = []
    for path in (Path(STATE_PATH), Path(EXAMPLE_STATE_PATH), Path(BASE_DIR) / ".env", Path(BASE_DIR) / ".env.local"):
        if path.exists() and path.is_file():
            candidates.append(path)
    data_dir = Path(DATA_DIR)
    if data_dir.exists():
        for path in sorted(data_dir.glob("*.json")):
            if path not in candidates:
                candidates.append(path)

    warnings = []
    secrets_dir = SECRETS_DIR
    provider_dir = SECRET_PROVIDER_DIR
    secret_file_records = []
    if secrets_dir.exists():
        try:
            mode = secrets_dir.stat().st_mode & 0o777
            warnings.append({
                "severity": "medium" if mode & 0o077 else "info",
                "kind": "secrets_dir_present",
                "location": ".secrets/",
                "mode": oct(mode),
                "action": "受限 fallback 目录必须为 0700；健康检查只看权限/文件名，不回显内容。",
            })
        except OSError:
            warnings.append({"severity": "medium", "kind": "secrets_dir_unreadable", "location": ".secrets/"})
        if provider_dir.exists():
            try:
                mode = provider_dir.stat().st_mode & 0o777
                warnings.append({
                    "severity": "medium" if mode & 0o077 else "info",
                    "kind": "secret_provider_dir_present",
                    "location": ".secrets/providers/",
                    "mode": oct(mode),
                    "action": "provider fallback 目录必须为 0700；key 文件必须为 0600 且不可是 symlink。",
                })
            except OSError:
                warnings.append({"severity": "medium", "kind": "secret_provider_dir_unreadable", "location": ".secrets/providers/"})
            for path in sorted(provider_dir.glob("*.key"))[:20]:
                rel = os.path.relpath(path, BASE_DIR)
                try:
                    is_link = path.is_symlink()
                    mode = path.stat().st_mode & 0o777
                    ok_perm = (not is_link) and path.is_file() and (mode & 0o077) == 0
                    secret_file_records.append({"location": rel, "mode": oct(mode), "restricted": ok_perm})
                    if not ok_perm:
                        warnings.append({
                            "severity": "high",
                            "kind": "secret_file_permission_unsafe",
                            "location": rel,
                            "mode": oct(mode),
                            "action": "拒绝使用权限不安全的 fallback key；请 chmod 600 且确认不是 symlink。",
                        })
                except OSError:
                    warnings.append({"severity": "medium", "kind": "secret_file_unreadable", "location": rel})
        # Backward-compatible JSON fallback metadata may exist; scan it as text/JSON because it should not hold plaintext values.
        try:
            for path in sorted(secrets_dir.glob("*.json"))[:8]:
                candidates.append(path)
        except OSError:
            pass

    risks = []
    files_scanned = []
    for path in candidates[:40]:
        rel = os.path.relpath(path, BASE_DIR)
        try:
            if path.stat().st_size > 2_000_000:
                warnings.append({"severity": "info", "kind": "file_skipped_large", "location": rel})
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            warnings.append({"severity": "medium", "kind": "file_unreadable", "location": rel})
            continue
        files_scanned.append(rel)
        file_risks = []
        if path.suffix.lower() == ".json":
            try:
                file_risks.extend(_scan_json_secret_fields(json.loads(text)))
            except Exception:
                file_risks.extend(_scan_text_secret_lines(text))
        else:
            file_risks.extend(_scan_text_secret_lines(text))
        for risk in file_risks[:20]:
            risk["location"] = rel
            risks.append(risk)

    env_names = []
    for name in sorted(os.environ):
        upper = name.upper()
        if upper.startswith("LINGTAI_SIMPLE_") and any(x in upper for x in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "BEARER")):
            env_names.append(name)
    if env_names:
        warnings.append({
            "severity": "info",
            "kind": "sensitive_env_slots_present",
            "env_names": env_names[:20],
            "action": "env slot 只作受限只读 fallback；不要在日志/报告/微信中回显变量值。",
        })

    high = sum(1 for r in risks if r.get("severity") == "high") + sum(1 for w in warnings if w.get("severity") == "high")
    medium = sum(1 for r in risks if r.get("severity") == "medium") + sum(1 for w in warnings if w.get("severity") == "medium")
    return {
        "ok": high == 0,
        "scanned_at": now_iso(),
        "keychain_available": keychain_available(),
        "policy": "Keychain-first; optional restricted env/.secrets fallback; no plaintext API key in JSON/log/API responses; scan returns only locations/fields/permissions, never values.",
        "fallback": {
            "env_prefix": SECRET_FALLBACK_ENV_PREFIX,
            "secret_dir": ".secrets/providers/",
            "dir_present": provider_dir.exists(),
            "secret_files": secret_file_records,
        },
        "summary": {"high": high, "medium": medium, "warnings": len(warnings), "files_scanned": len(files_scanned), "secret_files": len(secret_file_records)},
        "files_scanned": files_scanned,
        "risks": risks[:60],
        "warnings": warnings[:40],
    }


def key_last4(raw_key):
    """只取后四位用于展示；绝不存全量明文。"""
    if not raw_key:
        return None
    raw_key = raw_key.strip()
    if len(raw_key) <= 4:
        return "****"
    return raw_key[-4:]


def _safe_lingtai_address(address):
    """Validate a bare LingTai peer address (directory basename under `.lingtai/`)."""
    address = (address or "").strip()
    if not address or address in (".", ".."):
        return None
    if any(x in address for x in ("/", "\\", "\x00")):
        return None
    return address[:128]


def _lingtai_network_path():
    root = os.environ.get("LINGTAI_SIMPLE_NETWORK_DIR") or LINGTAI_NETWORK_DIR
    if not root:
        return None
    p = Path(root).expanduser().resolve()
    return p if p.is_dir() else None


def _mailbox_uuid():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"



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
    """是否能用 macOS Security.framework Keychain。

    LINGTAI_SIMPLE_DISABLE_KEYCHAIN=1 可用于自检/受限环境，强制走 env/.secrets fallback；
    这不会删除或读取已有 Keychain 项，只是让本进程不使用 Keychain。
    """
    if KEYCHAIN_DISABLED:
        return False
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
# 受限 .secrets / env fallback（Keychain-first）
# --------------------------------------------------------------------------
# 规则：
# - Keychain 始终优先。fallback 只有在显式勾选 allow_secret_fallback 时才会写入。
# - .secrets/providers/<provider>.key 必须是普通文件、非 symlink、mode 0600；目录 0700。
# - API/state/log 只记录 source/last4/slot 名，不返回或记录 secret value。
# - env slot 只读，不由本服务写入或删除。

def _provider_env_key_name(provider_id):
    safe = re.sub(r"[^A-Za-z0-9]", "_", str(provider_id or "")).upper()
    return SECRET_FALLBACK_ENV_PREFIX + safe


def _provider_secret_path(provider_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(provider_id or ""))
    if safe not in PROVIDER_IDS:
        raise ValueError("未知供应商")
    return SECRET_PROVIDER_DIR / f"{safe}.key"


def _mode(path):
    return path.stat().st_mode & 0o777


def _restricted_mode_ok(path, *, is_dir=False):
    try:
        if path.is_symlink():
            return False
        st = path.stat()
    except OSError:
        return False
    mode = st.st_mode & 0o777
    if is_dir:
        return (mode & 0o077) == 0
    return path.is_file() and (mode & 0o077) == 0


def _ensure_secret_fallback_dirs():
    SECRETS_DIR.mkdir(mode=0o700, exist_ok=True)
    SECRET_PROVIDER_DIR.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
        os.chmod(SECRET_PROVIDER_DIR, 0o700)
    except OSError:
        pass
    if not _restricted_mode_ok(SECRETS_DIR, is_dir=True) or not _restricted_mode_ok(SECRET_PROVIDER_DIR, is_dir=True):
        raise KeychainUnavailable(".secrets 目录权限不安全：必须限制为 0700，拒绝写入 fallback key。")


def secret_fallback_set(provider_id, raw_key):
    if not raw_key:
        raise KeychainUnavailable("fallback key 为空，拒绝写入。")
    _ensure_secret_fallback_dirs()
    path = _provider_secret_path(provider_id)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw_key.strip() + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    if not _restricted_mode_ok(path, is_dir=False):
        raise KeychainUnavailable("fallback key 文件权限不安全：必须限制为 0600。")
    return True


def secret_fallback_has(provider_id):
    try:
        path = _provider_secret_path(provider_id)
    except ValueError:
        return False
    return path.exists() and _restricted_mode_ok(path, is_dir=False)


def secret_fallback_get(provider_id):
    try:
        path = _provider_secret_path(provider_id)
    except ValueError:
        return None
    if not path.exists() or not _restricted_mode_ok(path, is_dir=False):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:
        return None


def secret_fallback_delete(provider_id):
    try:
        path = _provider_secret_path(provider_id)
    except ValueError:
        return True
    try:
        if path.exists() and not path.is_symlink():
            path.unlink()
        return True
    except OSError:
        return False


def provider_secret_status(provider_id):
    env_name = _provider_env_key_name(provider_id)
    env_present = bool(os.environ.get(env_name))
    kc_available = keychain_available()
    in_keychain = False
    if kc_available:
        try:
            in_keychain = keychain_has(provider_id)
        except Exception:
            in_keychain = False
    secret_file_present = secret_fallback_has(provider_id)
    source = "keychain" if in_keychain else ("env" if env_present else ("secret_file" if secret_file_present else None))
    return {
        "keychain_available": kc_available,
        "in_keychain": in_keychain,
        "env_slot": env_name,
        "env_slot_present": env_present,
        "secret_file_present": secret_file_present,
        "key_source": source,
        "configured": bool(source),
    }


def resolve_provider_api_key(provider_id):
    """Keychain-first, then env slot, then restricted .secrets file. Returns (api_key, source)."""
    if keychain_available():
        try:
            api_key = keychain_get(provider_id)
            if api_key:
                return api_key, "keychain"
        except Exception:
            pass
    env_name = _provider_env_key_name(provider_id)
    api_key = os.environ.get(env_name)
    if api_key:
        return api_key, "env"
    api_key = secret_fallback_get(provider_id)
    if api_key:
        return api_key, "secret_file"
    return None, None


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


# --------------------------------------------------------------------------
# 累计预算 / 成本面板（v0.21）
# --------------------------------------------------------------------------

def _float(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _money(value):
    return round(float(value or 0.0), 6)


def _today_key():
    return datetime.now(timezone.utc).date().isoformat()


def _parse_iso(ts):
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _cost_policy(state):
    base = default_state()["cost_policy"]
    policy = state.setdefault("cost_policy", base.copy())
    for k, v in base.items():
        policy.setdefault(k, v)
    policy.setdefault("provider_price_per_1m", DEFAULT_PROVIDER_PRICE_PER_1M)
    policy.setdefault("overrides", [])
    return policy


def public_cost_policy(state):
    policy = _cost_policy(state)
    return {
        "enabled": bool(policy.get("enabled", True)),
        "currency": "USD",
        "daily_cap_usd": _money(_float(policy.get("daily_cap_usd"), DEFAULT_DAILY_COST_CAP_USD)),
        "provider_call_cap_usd": _money(_float(policy.get("provider_call_cap_usd"), DEFAULT_PROVIDER_CALL_CAP_USD)),
        "task_cap_usd": _money(_float(policy.get("task_cap_usd"), DEFAULT_TASK_COST_CAP_USD)),
        "cc_run_cap_usd": _money(_float(policy.get("cc_run_cap_usd"), DEFAULT_CC_RUN_CAP_USD)),
        "long_run_seconds": int(_float(policy.get("long_run_seconds"), DEFAULT_LONG_RUN_SECONDS)),
        "over_cap_requires_approval": bool(policy.get("over_cap_requires_approval", True)),
        "provider_price_per_1m": policy.get("provider_price_per_1m", DEFAULT_PROVIDER_PRICE_PER_1M),
        "active_overrides": _active_budget_overrides(state),
    }


def _price_for_provider(state, provider_id):
    policy = _cost_policy(state)
    prices = policy.get("provider_price_per_1m") or DEFAULT_PROVIDER_PRICE_PER_1M
    item = dict(DEFAULT_PROVIDER_PRICE_PER_1M.get(provider_id) or DEFAULT_PROVIDER_PRICE_PER_1M.get("custom", {}))
    item.update(prices.get(provider_id) or {})
    return {"input": _float(item.get("input"), 1.0),
            "output": _float(item.get("output"), 1.0),
            "note": item.get("note") or "local estimate"}


def _usage_tokens(usage, prompt="", max_tokens=MODEL_CALL_MAX_TOKENS):
    usage = usage or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if input_tokens is None:
        input_tokens = max(1, len(prompt or "") // 4)
    if output_tokens is None:
        if total_tokens and total_tokens >= input_tokens:
            output_tokens = max(0, int(total_tokens) - int(input_tokens))
        else:
            output_tokens = max_tokens
    return int(input_tokens or 0), int(output_tokens or 0)


def estimate_model_cost_usd(state, provider_id, usage=None, prompt="", max_tokens=MODEL_CALL_MAX_TOKENS):
    price = _price_for_provider(state, provider_id)
    input_tokens, output_tokens = _usage_tokens(usage, prompt=prompt, max_tokens=max_tokens)
    cost = (input_tokens / 1_000_000.0) * price["input"] + (output_tokens / 1_000_000.0) * price["output"]
    return _money(cost), {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "price_per_1m_input": price["input"],
        "price_per_1m_output": price["output"],
        "price_note": price.get("note"),
        "estimated": usage is None,
    }


def _active_budget_overrides(state):
    now = datetime.now(timezone.utc)
    active = []
    overrides = _cost_policy(state).setdefault("overrides", [])
    kept = []
    for ov in overrides:
        expires = _parse_iso(ov.get("expires_at"))
        if expires and expires < now:
            continue
        kept.append(ov)
        active.append({k: ov.get(k) for k in ("id", "kind", "provider_id", "task_id", "estimated_usd", "reason", "expires_at")})
    if len(kept) != len(overrides):
        _cost_policy(state)["overrides"] = kept
    return active


def _has_budget_override(state, *, kind, provider_id=None, task_id=None):
    for ov in _active_budget_overrides(state):
        if ov.get("kind") not in (kind, "any"):
            continue
        if ov.get("provider_id") and provider_id and ov.get("provider_id") != provider_id:
            continue
        if ov.get("task_id") and task_id and ov.get("task_id") != task_id:
            continue
        return True
    return False


def cost_status(state):
    policy = public_cost_policy(state)
    today = _today_key()
    ledger = state.setdefault("cost_ledger", [])
    today_rows = [r for r in ledger if (r.get("created_at") or "")[:10] == today]
    today_total = _money(sum(_float(r.get("estimated_usd"), 0.0) for r in today_rows))
    by_provider = {}
    by_kind = {}
    for r in today_rows:
        provider = r.get("provider_id") or "(none)"
        kind = r.get("kind") or "unknown"
        by_provider[provider] = _money(by_provider.get(provider, 0.0) + _float(r.get("estimated_usd"), 0.0))
        by_kind[kind] = _money(by_kind.get(kind, 0.0) + _float(r.get("estimated_usd"), 0.0))
    warnings = []
    daily_cap = _float(policy.get("daily_cap_usd"), DEFAULT_DAILY_COST_CAP_USD)
    if daily_cap > 0:
        ratio = today_total / daily_cap
        if ratio >= 1:
            warnings.append({"severity": "high", "kind": "daily_cap_exceeded", "message": f"今日估算成本 ${today_total:.4f} 已超过日上限 ${daily_cap:.4f}"})
        elif ratio >= 0.8:
            warnings.append({"severity": "medium", "kind": "daily_cap_near", "message": f"今日估算成本 ${today_total:.4f} 已接近日上限 ${daily_cap:.4f}"})
    long_run_seconds = int(_float(policy.get("long_run_seconds"), DEFAULT_LONG_RUN_SECONDS))
    now = datetime.now(timezone.utc)
    for r in state.get("cc_runs", []):
        if r.get("status") == "运行中":
            started = _parse_iso(r.get("started_at") or r.get("created_at"))
            if started and (now - started).total_seconds() > long_run_seconds:
                warnings.append({"severity": "medium", "kind": "long_running_cc", "message": f"Claude Code run {r.get('id')} 已运行超过 {long_run_seconds}s"})
    pending_budget = [a for a in state.get("approvals", []) if a.get("action") == "budget_override" and a.get("status") == "待确认"]
    return {
        "currency": "USD",
        "today": today,
        "today_total_usd": today_total,
        "daily_cap_usd": _money(daily_cap),
        "by_provider": by_provider,
        "by_kind": by_kind,
        "ledger_count": len(ledger),
        "pending_budget_approvals": len(pending_budget),
        "warnings": warnings,
        "last_entries": ledger[:10],
    }


def record_cost_event(state, *, kind, provider_id="", task_id="", estimated_usd=0.0, usage=None, source="local_estimate", note="", metadata=None):
    entry = {
        "id": new_id("cost"),
        "created_at": now_iso(),
        "kind": kind,
        "provider_id": provider_id or "",
        "task_id": task_id or "",
        "estimated_usd": _money(estimated_usd),
        "currency": "USD",
        "usage": usage or None,
        "source": source,
        "note": redact(note or ""),
        "metadata": metadata or {},
    }
    state.setdefault("cost_ledger", []).insert(0, entry)
    state["cost_ledger"] = state["cost_ledger"][:300]
    log_event(state, f"成本账本新增：{kind} / {provider_id or '-'} ≈ ${entry['estimated_usd']:.6f}", kind="cost")
    return entry


def _pending_budget_approval_exists(state, *, kind, provider_id=None, task_id=None):
    for ap in state.get("approvals", []):
        if ap.get("action") != "budget_override" or ap.get("status") != "待确认":
            continue
        if ap.get("cost_kind") != kind:
            continue
        if provider_id and ap.get("cost_provider_id") != provider_id:
            continue
        if task_id and ap.get("cost_task_id") != task_id:
            continue
        return ap
    return None


def budget_preflight(state, *, kind, provider_id="", task_id="", estimated_usd=0.0, note=""):
    policy = _cost_policy(state)
    if not policy.get("enabled", True):
        return None
    estimated_usd = _money(estimated_usd)
    if estimated_usd <= 0:
        return None
    if _has_budget_override(state, kind=kind, provider_id=provider_id, task_id=task_id):
        return None
    reasons = []
    daily_cap = _float(policy.get("daily_cap_usd"), DEFAULT_DAILY_COST_CAP_USD)
    today_total = cost_status(state).get("today_total_usd", 0.0)
    if daily_cap > 0 and today_total + estimated_usd > daily_cap:
        reasons.append(f"今日累计 ${today_total:.4f} + 本次估算 ${estimated_usd:.4f} 将超过日上限 ${daily_cap:.4f}")
    if kind == "model_call":
        cap = _float(policy.get("provider_call_cap_usd"), DEFAULT_PROVIDER_CALL_CAP_USD)
        if cap > 0 and estimated_usd > cap:
            reasons.append(f"本次模型调用估算 ${estimated_usd:.4f} 超过单次 provider 上限 ${cap:.4f}")
    if kind.startswith("claude_code"):
        cap = _float(policy.get("cc_run_cap_usd"), DEFAULT_CC_RUN_CAP_USD)
        if cap > 0 and estimated_usd > cap:
            reasons.append(f"本次 Claude Code 预留 ${estimated_usd:.4f} 超过单次 CC 上限 ${cap:.4f}")
    if task_id:
        cap = _float(policy.get("task_cap_usd"), DEFAULT_TASK_COST_CAP_USD)
        task_total = sum(_float(r.get("estimated_usd"), 0.0) for r in state.get("cost_ledger", []) if r.get("task_id") == task_id)
        if cap > 0 and task_total + estimated_usd > cap:
            reasons.append(f"任务 {task_id} 累计 ${task_total:.4f} + 本次 ${estimated_usd:.4f} 将超过任务上限 ${cap:.4f}")
    if not reasons:
        return None
    if not policy.get("over_cap_requires_approval", True):
        log_event(state, "预算越线但策略允许继续：" + "；".join(reasons), kind="cost")
        return None
    existing = _pending_budget_approval_exists(state, kind=kind, provider_id=provider_id, task_id=task_id)
    if not existing:
        detail = "\n".join([*reasons, f"动作：{kind}", f"provider：{provider_id or '-'}", f"task：{task_id or '-'}", f"说明：{note or '-'}"])
        add_approval(state, {
            "action": "budget_override",
            "title": f"预算/成本越线确认：{kind} {provider_id or ''}".strip(),
            "detail": detail,
            "preview": detail + "\n\n确认后仅生成一次 30 分钟短时放行；不会自动发起外部调用，需要用户重新点击原动作。",
            "cost_kind": kind,
            "cost_provider_id": provider_id,
            "cost_task_id": task_id,
            "cost_estimated_usd": str(estimated_usd),
            "cost_cap_usd": str(daily_cap),
            "cost_reason": "；".join(reasons),
        })
    return "预算/成本策略已拦截：" + "；".join(reasons) + "。已加入确认队列；确认后请重新执行原动作。"


def budget_override_apply_real(state, ap):
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    ov = {
        "id": ap.get("id") or new_id("costovr"),
        "kind": ap.get("cost_kind") or "any",
        "provider_id": ap.get("cost_provider_id") or "",
        "task_id": ap.get("cost_task_id") or "",
        "estimated_usd": _money(_float(ap.get("cost_estimated_usd"), 0.0)),
        "reason": redact(ap.get("cost_reason") or "budget override"),
        "approved_at": now_iso(),
        "expires_at": expires_at,
    }
    _cost_policy(state).setdefault("overrides", []).insert(0, ov)
    log_event(state, f"预算/成本短时放行：{ov['kind']} / {ov.get('provider_id') or '-'}，30 分钟内有效", kind="cost")
    return ov, None


def update_cost_policy(state, payload):
    policy = _cost_policy(state)
    for key in ("daily_cap_usd", "provider_call_cap_usd", "task_cap_usd", "cc_run_cap_usd"):
        if key in payload:
            val = _float(payload.get(key), policy.get(key))
            if val < 0:
                return None, f"{key} 不能为负数"
            policy[key] = _money(val)
    if "long_run_seconds" in payload:
        val = int(_float(payload.get("long_run_seconds"), policy.get("long_run_seconds")))
        if val < 60:
            return None, "long_run_seconds 不能小于 60 秒"
        policy["long_run_seconds"] = val
    if "enabled" in payload:
        policy["enabled"] = bool(payload.get("enabled"))
    if "over_cap_requires_approval" in payload:
        policy["over_cap_requires_approval"] = bool(payload.get("over_cap_requires_approval"))
    if payload.get("reset_ledger"):
        state["cost_ledger"] = []
        log_event(state, "成本账本已清空（本地记录，不影响供应商真实账单）", kind="cost")
    log_event(state, "已更新预算/成本策略", kind="cost")
    return {"policy": public_cost_policy(state), "status": cost_status(state)}, None


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
            "name": "圆酱专属轻量版灵台 / LingTai Simple v0.21",
            "owner": "圆酱 / Runyuan",
            "localhost_only": True,
            "created_at": now_iso(),
            "max_agents": MAX_AGENTS,
        },
        "agents": [],
        "tasks": [],
        "approvals": [],
        "providers": [],       # 已配置的供应商（脱敏）
        "cost_policy": {       # v0.21 累计预算/成本策略；估算值，不连接供应商账单
            "enabled": True,
            "currency": "USD",
            "daily_cap_usd": DEFAULT_DAILY_COST_CAP_USD,
            "provider_call_cap_usd": DEFAULT_PROVIDER_CALL_CAP_USD,
            "task_cap_usd": DEFAULT_TASK_COST_CAP_USD,
            "cc_run_cap_usd": DEFAULT_CC_RUN_CAP_USD,
            "long_run_seconds": DEFAULT_LONG_RUN_SECONDS,
            "over_cap_requires_approval": True,
            "provider_price_per_1m": DEFAULT_PROVIDER_PRICE_PER_1M,
            "overrides": [],
        },
        "cost_ledger": [],     # 真实模型/Claude Code 等可能计费动作的本地估算账本
        "wechat_inbox": [],    # 微信入口收到的任务队列（v0.21 支持真实桥接写入）
        "wechat_outbox": [],   # 待桥接者原路发回微信的回复（不由本服务直接轮询/发送，避免双 poller）
        "wechat_bridge": {
            "mode": "lingtai_mcp_bridge",
            "status": "ready",
            "runner_contract": "no_second_poller",
            "pending_endpoint": "/api/wechat/bridge/pending",
            "incoming_endpoint": "/api/wechat/bridge/incoming",
            "mark_sent_endpoint": "/api/wechat/bridge/mark_sent",
            "note": "由当前 LingTai 的 WeChat MCP 作为唯一真实收发桥；本服务只提供 localhost 控制端点和 runner 合约，不启动第二 poller。",
        },
        "router_runs": [],     # v0.21 统一 Task Router 运行记录：一句话 -> route -> task/agent/mailbox/cc/shougong
        "worker_requests": [],  # v0.21 受控 worker 调度：daemon/Codex/Claude/avatar handoff -> approval -> real LingTai mailbox -> result collection
        "cc_runs": [],          # Claude Code 运行记录（v0.21 真实接入 L1/L2/L3/L4/L5，并新增多 agent/洞察/心流本地回环）
        "orchestrations": [],   # 多 agent / 子灵编排批次（真实本地状态，不伪装外部执行）
        "insights": [],         # 洞察记录：由当前任务/风险/卡点生成的本地分析
        "soul_flows": [],       # 心流记录：阶段性回环、自省与续功入口
        "lingtai_runtime": {
            "mode": "internal_mailbox_bridge",
            "status": "ready" if LINGTAI_NETWORK_DIR else "not_found",
            "network_dir": LINGTAI_NETWORK_DIR,
            "sender": LINGTAI_MAIL_SENDER,
            "reply_inbox": LINGTAI_REPLY_INBOX,
            "note": "v0.21 起支持 Simple → LingTai 内部邮箱派发，并可从 reply_inbox 回收真实 agent 回复。",
        },
        "lingtai_dispatches": [], # 已写入 LingTai 内部邮箱 outbox 的真实派活记录
        "lingtai_mail_results": [], # 从真实 LingTai reply_inbox 只读回收的 agent 回复
        "lingtai_lifecycle_events": [], # 真实 lifecycle signal/CPR 操作记录
        "lingtai_avatar_events": [], # 真实 avatar spawn/绑定事件记录
        "lingtai_memory_scans": [], # 真实 LingTai pad/knowledge/skill 只读索引记录
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
    """兼容旧版本 state.json：补齐 v0.21 新字段，避免升级后丢状态。"""
    base = default_state()
    state.setdefault("meta", base["meta"])
    state["meta"]["name"] = "圆酱专属轻量版灵台 / LingTai Simple v0.21"
    state["meta"]["max_agents"] = MAX_AGENTS
    state.setdefault("agents", [])
    state.setdefault("tasks", [])
    state.setdefault("approvals", [])
    state.setdefault("providers", [])
    state.setdefault("cost_policy", base["cost_policy"])
    for k, v in base["cost_policy"].items():
        state["cost_policy"].setdefault(k, v)
    state.setdefault("cost_ledger", [])
    state.setdefault("wechat_inbox", [])
    state.setdefault("wechat_outbox", [])
    state.setdefault("wechat_bridge", base["wechat_bridge"])
    state["wechat_bridge"].setdefault("runner_contract", "no_second_poller")
    state["wechat_bridge"].setdefault("pending_endpoint", "/api/wechat/bridge/pending")
    state["wechat_bridge"].setdefault("incoming_endpoint", "/api/wechat/bridge/incoming")
    state["wechat_bridge"].setdefault("mark_sent_endpoint", "/api/wechat/bridge/mark_sent")
    state.setdefault("router_runs", [])
    state.setdefault("worker_requests", [])
    state.setdefault("cc_runs", [])
    state.setdefault("orchestrations", [])
    state.setdefault("insights", [])
    state.setdefault("soul_flows", [])
    state.setdefault("lingtai_runtime", base["lingtai_runtime"])
    state["lingtai_runtime"]["reply_inbox"] = LINGTAI_REPLY_INBOX
    state.setdefault("lingtai_dispatches", [])
    state.setdefault("lingtai_mail_results", [])
    state.setdefault("lingtai_lifecycle_events", [])
    state.setdefault("lingtai_avatar_events", [])
    state.setdefault("lingtai_memory_scans", [])
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
    lingtai_address = _safe_lingtai_address(payload.get("lingtai_address") or payload.get("real_address") or "") or ""
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
        "lingtai_address": lingtai_address,  # 可选：真实 LingTai agent 地址；v0.21 起可派发内部邮箱任务
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

    # 本地编排执行：低风险记录为完成，敏感任务进确认队列
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
        task["result"] = f"已完成本地编排记录：{desc[:60]}"
        agent["status"] = "待命"
        log_event(state, f"{agent['name']} 完成本地编排记录")
    return task, None


def _task_counts(state):
    tasks = state.get("tasks", [])
    return {
        "total": len(tasks),
        "active": len([t for t in tasks if t.get("status") in ("排队中", "执行中", "等确认")]),
        "pending_confirm": len([t for t in tasks if t.get("status") == "等确认"]),
        "blocked": len([t for t in tasks if t.get("status") in ("卡住", "失败")]),
        "done": len([t for t in tasks if t.get("status") == "完成"]),
    }


def _agent_digest(agent):
    return f"{agent.get('name','未命名')}（{agent.get('role','')}｜{agent.get('status','')}｜context {agent.get('context_pressure',0)}%）"


def generate_insights(state, payload=None):
    """生成“洞察”：基于当前本地状态的确定性分析，不调用外部模型、不烧钱。"""
    payload = payload or {}
    focus = (payload.get("focus") or "").strip()
    agents = state.get("agents", [])
    pending = [a for a in state.get("approvals", []) if a.get("status") == "待确认"]
    active = [t for t in state.get("tasks", []) if t.get("status") in ("排队中", "执行中", "等确认")]
    high_pressure = [a for a in agents if int(a.get("context_pressure") or 0) >= 70]
    stalled = [t for t in state.get("tasks", []) if t.get("status") in ("卡住", "失败")]
    recent_sensitive = [t for t in state.get("tasks", [])[:12] if t.get("risk") == "sensitive"]

    findings = []
    if not agents:
        findings.append({"level": "high", "title": "还没有子灵", "evidence": "agents=0", "next_action": "先新建主控灵/洞察灵/执行灵，才能形成多 agent 编排。"})
    if pending:
        findings.append({"level": "high", "title": "有待确认动作", "evidence": f"pending_approvals={len(pending)}", "next_action": "先处理确认队列；PR/merge/rollback/外发类动作不要绕过确认闸。"})
    if high_pressure:
        findings.append({"level": "medium", "title": "有子灵 context 压力偏高", "evidence": "；".join(_agent_digest(a) for a in high_pressure[:3]), "next_action": "生成收功单或拆分任务，避免把一个子灵压成万能大模型。"})
    if active:
        findings.append({"level": "medium", "title": "仍有进行中/待处理任务", "evidence": f"active_tasks={len(active)}", "next_action": "让主控按子灵汇总：谁负责、当前状态、下一步是什么。"})
    if stalled:
        findings.append({"level": "high", "title": "存在卡住/失败任务", "evidence": "；".join(t.get("description", "")[:30] for t in stalled[:3]), "next_action": "只修最小失败层：日志→复现→补丁→自检，不整炉重炼。"})
    if recent_sensitive:
        findings.append({"level": "medium", "title": "近期有敏感动作", "evidence": f"sensitive_tasks={len(recent_sensitive)}", "next_action": "继续保持二次确认；GitHub/rollback/外发副作用要写清不可逆边界。"})
    if focus:
        findings.append({"level": "info", "title": "本次洞察焦点", "evidence": redact(focus[:160]), "next_action": "围绕这个焦点安排子灵：洞察灵看风险，执行灵做落地，审校灵查边界。"})
    if not findings:
        findings.append({"level": "info", "title": "当前炉火平稳", "evidence": "无待确认、无高压、无卡住任务", "next_action": "可以继续派下一个小任务，或生成心流做阶段回环。"})

    insight = {
        "id": new_id("insight"),
        "created_at": now_iso(),
        "focus": redact(focus),
        "findings": findings[:8],
        "summary": "；".join(f["title"] for f in findings[:4]),
        "source": "local_state_rules",
    }
    state.setdefault("insights", []).insert(0, insight)
    state["insights"] = state["insights"][:50]
    log_event(state, f"生成洞察：{insight['summary'][:80]}", kind="insight")
    return insight, None


def generate_soul_flow(state, payload=None):
    """生成“心流”：把任务、洞察、确认队列收束成可返回的阶段性自省。"""
    payload = payload or {}
    trigger = (payload.get("trigger") or "manual").strip() or "manual"
    counts = _task_counts(state)
    agents = state.get("agents", [])
    latest_insight = (state.get("insights") or [None])[0]
    pending = [a for a in state.get("approvals", []) if a.get("status") == "待确认"]
    high = [a for a in agents if int(a.get("context_pressure") or 0) >= 70]

    lines = [
        "心流回环：我先把现场收成一个圆，再继续向外做。",
        f"触发：{trigger}。当前有 {len(agents)} 个子灵、{counts['active']} 个进行中/待处理任务、{len(pending)} 个待确认动作。",
    ]
    if agents:
        lines.append("子灵分工：" + "；".join(_agent_digest(a) for a in agents[:5]))
    if latest_insight:
        lines.append("最近洞察：" + latest_insight.get("summary", ""))
    if pending:
        lines.append("确认闸提醒：先处理确认队列，所有外部副作用都要二次确认。")
    if high:
        lines.append("护元提醒：有子灵上下文压力偏高，下一步应拆小或收功，不要继续堆大任务。")
    if not pending and counts["active"] == 0:
        lines.append("当前没有必须立刻处理的卡点，可以安排下一轮多 agent 小闭环。")
    lines.append("续功入口：发“洞察”看风险；发“多agent <目标>”拆分子灵；发“收功”保存阶段成果。")

    flow = {
        "id": new_id("soul"),
        "created_at": now_iso(),
        "trigger": redact(trigger),
        "text": "\n".join(lines),
        "source": "local_state_reflection",
        "task_counts": counts,
    }
    state.setdefault("soul_flows", []).insert(0, flow)
    state["soul_flows"] = state["soul_flows"][:50]
    log_event(state, f"生成心流：{trigger}", kind="soul")
    return flow, None



def _lingtai_agent_dir(address):
    root = _lingtai_network_path()
    address = _safe_lingtai_address(address)
    if not root or not address:
        return None
    return root / address


def _heartbeat_info(agent_dir):
    hb = agent_dir / ".agent.heartbeat"
    if not hb.exists():
        return {"heartbeat": False, "alive": False, "age_seconds": None}
    try:
        raw = hb.read_text(encoding="utf-8").strip()
        ts = float(raw) if raw else hb.stat().st_mtime
    except Exception:
        ts = hb.stat().st_mtime
    age = max(0.0, time.time() - ts)
    return {"heartbeat": True, "alive": age <= LINGTAI_HEARTBEAT_FRESH_SECONDS, "age_seconds": round(age, 1)}


def list_lingtai_agents():
    """Discover real LingTai agents in the surrounding `.lingtai` network (read-only)."""
    root = _lingtai_network_path()
    if not root:
        return []
    rows = []
    try:
        children = sorted(root.iterdir(), key=lambda x: x.name)
    except OSError:
        return []
    for child in children:
        manifest_path = child / ".agent.json"
        if not child.is_dir() or not manifest_path.exists():
            continue
        try:
            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        address = meta.get("address") or child.name
        if not _safe_lingtai_address(address):
            continue
        hb = _heartbeat_info(child)
        rows.append({
            "address": address,
            "agent_name": meta.get("agent_name") or address,
            "nickname": meta.get("nickname"),
            "state": meta.get("state"),
            "alive": hb["alive"],
            "heartbeat_age_seconds": hb["age_seconds"],
            "model": ((meta.get("llm") or {}).get("model")),
            "provider": ((meta.get("llm") or {}).get("provider")),
            "molt_count": meta.get("molt_count"),
        })
    return rows


def _drop_lingtai_mail(*, to_address, subject, message, sender=None, via="lingtai-simple"):
    """Write one real internal-mail message to `<sender>/mailbox/outbox/<id>/message.json`.

    This follows the documented wake-by-mailbox-drop contract. The LingTai kernel
    mailman later claims the outbox folder and delivers it to the recipient inbox.
    """
    root = _lingtai_network_path()
    if not root:
        return None, "找不到 .lingtai 网络目录；请设置 LINGTAI_SIMPLE_NETWORK_DIR。"
    to_address = _safe_lingtai_address(to_address)
    sender = _safe_lingtai_address(sender or LINGTAI_MAIL_SENDER)
    if not to_address:
        return None, "真实 LingTai 收件地址不合法"
    if not sender:
        return None, "LingTai Simple 邮件 sender 不合法"
    recipient_dir = root / to_address
    if not (recipient_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{to_address}"
    sender_dir = root / sender
    outbox_root = sender_dir / "mailbox" / "outbox"
    outbox_root.mkdir(parents=True, exist_ok=True)
    mailbox_id = _mailbox_uuid()
    final_dir = outbox_root / mailbox_id
    tmp_dir = outbox_root / (mailbox_id + ".tmp")
    msg = {
        "id": mailbox_id,
        "_mailbox_id": mailbox_id,
        "from": sender,
        "to": [to_address],
        "cc": [],
        "subject": redact(subject or "LingTai Simple 任务派发"),
        "message": redact(message or ""),
        "type": "normal",
        "received_at": now_iso(),
        "identity": {
            "address": sender,
            "agent_name": "LingTai Simple",
            "via": via,
        },
    }
    if tmp_dir.exists() or final_dir.exists():
        return None, "邮箱 ID 冲突，请重试"
    tmp_dir.mkdir(parents=True)
    try:
        (tmp_dir / "message.json").write_text(json.dumps(msg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp_dir), str(final_dir))
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None, f"写入 LingTai outbox 失败：{e}"
    return {
        "mailbox_id": mailbox_id,
        "to": to_address,
        "from": sender,
        "subject": msg["subject"],
        "outbox_path": str(final_dir),
    }, None


def _task_by_id(state, task_id):
    for task in state.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def dispatch_task_to_lingtai(state, payload):
    """Real bridge: queue a Simple task into a real LingTai agent mailbox."""
    if not payload.get("confirm_dispatch"):
        return None, "派发到真实 LingTai agent 会唤醒/占用真实 agent；请传 confirm_dispatch=true。"
    task_id = payload.get("task_id") or ""
    task = _task_by_id(state, task_id) if task_id else None
    agent = find_agent(state, task.get("agent_id")) if task else None
    address = _safe_lingtai_address(payload.get("address") or (agent or {}).get("lingtai_address") or "")
    if not address:
        return None, "请提供真实 LingTai agent 地址（address），或先给本地灵绑定 lingtai_address。"
    body = (payload.get("message") or "").strip()
    if task:
        body = body or task.get("description", "")
    if not body:
        return None, "派发内容不能为空"
    subject = (payload.get("subject") or "").strip()
    if not subject:
        subject = "LingTai Simple 派活：" + _bounded(body.replace("\n", " "), 48)
    message = (
        "【LingTai Simple v0.21 真实内部邮箱派活】\n\n"
        f"来源：圆酱专属轻量版灵台（localhost Simple UI / WeChat bridge）\n"
        f"本地任务 ID：{task_id or 'manual'}\n"
        f"本地灵：{(agent or {}).get('name') or '未绑定'}\n\n"
        "请按真实 LingTai agent 能力执行；完成、卡住或需要确认时，请内部邮件回复 mimo-2-5-pro。\n"
        "不要假装完成；若涉及外部副作用（push/PR/merge/发消息/删除/回滚），必须先请求确认。\n\n"
        "任务内容：\n" + body
    )
    result, err = _drop_lingtai_mail(to_address=address, subject=subject, message=message,
                                    via="lingtai-simple-v0.21")
    if err:
        return None, err
    dispatch = {
        "id": new_id("dispatch"),
        "created_at": now_iso(),
        "task_id": task_id,
        "agent_id": (agent or {}).get("id"),
        "local_agent_name": (agent or {}).get("name"),
        "to": result["to"],
        "from": result["from"],
        "subject": result["subject"],
        "mailbox_id": result["mailbox_id"],
        "outbox_path": result["outbox_path"],
        "status": "queued_to_lingtai_outbox",
    }
    state.setdefault("lingtai_dispatches", []).insert(0, dispatch)
    state["lingtai_dispatches"] = state["lingtai_dispatches"][:80]
    state.setdefault("lingtai_runtime", default_state()["lingtai_runtime"])["last_dispatch_at"] = dispatch["created_at"]
    if task:
        task["status"] = "已派发"
        task["result"] = f"已写入真实 LingTai 内部邮箱 outbox：{result['from']} → {result['to']} / {result['mailbox_id']}"
    if agent:
        agent["status"] = "正在干"
    log_event(state, f"真实 LingTai 邮箱派发：{result['from']} → {result['to']} / {result['mailbox_id']}", kind="lingtai_runtime")
    return dispatch, None



def _read_lingtai_message_file(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    mailbox_id = data.get("_mailbox_id") or data.get("id") or path.parent.name
    body = data.get("message") or data.get("body") or ""
    subject = data.get("subject") or ""
    sender = data.get("from") or data.get("sender") or ""
    received = data.get("received_at") or data.get("date") or ""
    return {
        "mailbox_id": mailbox_id,
        "file_path": str(path),
        "from": sender,
        "to": data.get("to") or [],
        "subject": redact(subject),
        "message": redact(body),
        "received_at": received,
    }


def _match_reply_to_dispatch(msg, dispatches):
    text = f"{msg.get('subject','')}\n{msg.get('message','')}"
    sender = msg.get("from") or ""
    for d in dispatches:
        mid = d.get("mailbox_id") or ""
        worker_id = d.get("worker_request_id") or ""
        subj = d.get("subject") or ""
        to_addr = d.get("to") or ""
        if worker_id and worker_id in text:
            return d
        if mid and mid in text:
            return d
        if sender and to_addr and sender == to_addr and subj:
            normalized = (msg.get("subject") or "").replace("Re:", "").replace("回复:", "").strip()
            if normalized == subj or subj in (msg.get("subject") or ""):
                return d
        if sender and to_addr and sender == to_addr and "LingTai Simple" in text:
            return d
    return None


def _worker_kind_label(kind):
    labels = {
        "daemon": "daemon/分神",
        "codex": "Codex/代码苦力",
        "claude": "Claude Code/代码苦力",
        "avatar": "real avatar/长期分身",
        "code_worker": "代码苦力",
    }
    return labels.get(kind or "", kind or "worker")


def _infer_worker_kind(route_type, text, payload=None):
    payload = payload or {}
    forced = (payload.get("worker_kind") or "").strip().lower()
    if forced in ("daemon", "codex", "claude", "avatar", "code_worker"):
        return forced
    lower = (text or "").lower()
    if route_type == "daemon_plan" or any(k in lower for k in ("daemon", "分神", "临时分析", "扫一遍")):
        return "daemon"
    if "codex" in lower:
        return "codex"
    if "avatar" in lower or "分身" in lower or "子agent" in lower or "子 agent" in lower:
        return "avatar"
    if "claude" in lower:
        return "claude"
    return "code_worker"


def _worker_request_by_id(state, worker_request_id):
    for wr in state.setdefault("worker_requests", []):
        if wr.get("id") == worker_request_id:
            return wr
    return None


def create_controlled_worker_request(state, payload):
    """Create an approval-gated worker handoff request; approval writes real LingTai internal mail."""
    text = (payload.get("text") or payload.get("description") or payload.get("message") or "").strip()
    if not text:
        return None, "worker 调度内容不能为空"
    route_type = payload.get("route_type") or _classify_route(text, payload)
    kind = _infer_worker_kind(route_type, text, payload)
    controller = _safe_lingtai_address(payload.get("controller") or LINGTAI_WORKER_CONTROLLER)
    if not controller:
        return None, "worker controller 地址不合法；请设置 LINGTAI_SIMPLE_WORKER_CONTROLLER"
    agent = _first_available_agent(state, fallback_name=f"{_worker_kind_label(kind)}调度灵", fallback_role="受控 worker 调度")
    task, err = assign_task(state, {
        "agent_id": agent["id"],
        "description": text,
        "source": payload.get("source") or "task_router",
        "risk": "low",
    })
    if err:
        return None, err
    task["status"] = "等待 worker 调度确认"
    task["result"] = "已创建受控 worker 调度请求；确认后才会写入真实 LingTai 内部邮箱。"
    agent["status"] = "等待确认"
    wr = {
        "id": new_id("worker"),
        "created_at": now_iso(),
        "kind": kind,
        "label": _worker_kind_label(kind),
        "status": "awaiting_approval",
        "controller": controller,
        "description": redact(text),
        "source": payload.get("source") or "task_router",
        "route_id": payload.get("route_id") or "",
        "task_id": task["id"],
        "agent_id": agent["id"],
        "inbound_id": payload.get("inbound_id") or "",
        "user_id": payload.get("user_id") or "",
        "reply_to_message_id": payload.get("reply_to_message_id") or payload.get("message_id") or "",
        "steps": ["created", "approval_required"],
    }
    state.setdefault("worker_requests", []).insert(0, wr)
    state["worker_requests"] = state["worker_requests"][:80]
    detail = (
        f"worker 类型：{wr['label']}\n"
        f"controller：{controller}\n"
        f"本地任务：{task['id']}\n"
        f"任务内容：{text}\n\n"
        "确认后动作：向真实 LingTai 内部邮箱写一封调度信，请 controller agent 受控执行；"
        "不会由 Simple 自己启动第二微信 poller，也不会绕过 controller 的确认/权限纪律。"
    )
    ap = add_approval(state, {
        "action": "worker_dispatch",
        "title": f"受控 worker 调度：{wr['label']} / {text[:28]}",
        "detail": detail,
        "task_id": task["id"],
        "agent_id": agent["id"],
        "worker_request_id": wr["id"],
        "worker_kind": kind,
        "worker_controller": controller,
        "worker_description": text,
        "worker_route_id": wr.get("route_id", ""),
        "worker_inbound_id": wr.get("inbound_id", ""),
        "worker_user_id": wr.get("user_id", ""),
        "worker_reply_to_message_id": wr.get("reply_to_message_id", ""),
    })
    wr["approval_id"] = ap["id"]
    task["approval_id"] = ap["id"]
    log_event(state, f"受控 worker 调度请求已创建：{wr['id']} / {wr['label']}", kind="worker")
    return wr, None


def worker_request_apply_real(state, ap):
    """Approval executor: write one real internal-mail request to the worker controller."""
    worker_request_id = ap.get("worker_request_id") or ""
    wr = _worker_request_by_id(state, worker_request_id)
    if not wr:
        return None, "找不到 worker_request；拒绝执行调度"
    if wr.get("status") not in ("awaiting_approval", "dispatch_failed"):
        return None, f"worker_request 当前状态为 {wr.get('status')}，不能重复调度"
    controller = _safe_lingtai_address(ap.get("worker_controller") or wr.get("controller") or LINGTAI_WORKER_CONTROLLER)
    if not controller:
        return None, "worker controller 地址不合法"
    desc = ap.get("worker_description") or wr.get("description") or ""
    kind = ap.get("worker_kind") or wr.get("kind") or "worker"
    subject = f"LingTai Simple 受控 worker 调度：{_worker_kind_label(kind)} / {worker_request_id}"
    message = (
        "【LingTai Simple v0.21 受控 worker 调度】\n\n"
        f"worker_request_id：{worker_request_id}\n"
        f"本地任务 ID：{wr.get('task_id') or ap.get('task_id') or ''}\n"
        f"请求类型：{_worker_kind_label(kind)}\n"
        f"来源：{wr.get('source') or 'task_router'}\n\n"
        "请你作为真实 LingTai controller agent 受控执行：\n"
        "1. 若是 daemon/分神任务：按 daemon 能力派一次临时分神并回收结论。\n"
        "2. 若是 Codex/Claude/代码苦力：按本机可用工具和权限闸执行，不要绕过成本/副作用确认。\n"
        "3. 若是 real avatar/长期分身：只在任务确需长期学习时再创建/派发，且遵守 avatar 安全边界。\n"
        "4. 完成、卡住或需要人类确认时，请内部邮件回复 mimo-2-5-pro，并在正文包含 worker_request_id。\n"
        "5. 不要假装完成；push/PR/merge/发消息/删除/回滚等外部副作用必须先请求确认。\n\n"
        "任务内容：\n" + desc
    )
    result, err = _drop_lingtai_mail(to_address=controller, subject=subject, message=message,
                                    via="lingtai-simple-v0.21-worker")
    if err:
        wr["status"] = "dispatch_failed"
        wr["error"] = err
        return None, err
    wr.update({
        "status": "dispatched_to_controller",
        "controller": controller,
        "mailbox_id": result.get("mailbox_id"),
        "outbox_path": result.get("outbox_path"),
        "dispatched_at": now_iso(),
    })
    wr.setdefault("steps", []).append("queued_to_lingtai_controller")
    dispatch = {
        "id": new_id("dispatch"),
        "created_at": now_iso(),
        "task_id": wr.get("task_id") or ap.get("task_id"),
        "agent_id": wr.get("agent_id") or ap.get("agent_id"),
        "local_agent_name": (find_agent(state, wr.get("agent_id") or ap.get("agent_id")) or {}).get("name"),
        "to": result["to"],
        "from": result["from"],
        "subject": result["subject"],
        "mailbox_id": result["mailbox_id"],
        "outbox_path": result["outbox_path"],
        "status": "queued_to_worker_controller",
        "worker_request_id": worker_request_id,
        "worker_kind": kind,
    }
    state.setdefault("lingtai_dispatches", []).insert(0, dispatch)
    state["lingtai_dispatches"] = state["lingtai_dispatches"][:80]
    task = _task_by_id(state, wr.get("task_id") or ap.get("task_id"))
    if task:
        task["status"] = "已派发给 worker controller"
        task["result"] = f"已写入真实 LingTai 内部邮箱：{result['from']} → {result['to']} / {result['mailbox_id']}"
    ag = find_agent(state, wr.get("agent_id") or ap.get("agent_id"))
    if ag:
        ag["status"] = "正在干"
    log_event(state, f"受控 worker 调度已写入真实内部邮箱：{worker_request_id} → {controller}", kind="worker")
    return {"worker_request_id": worker_request_id, "mailbox_id": result.get("mailbox_id"), "controller": controller}, None


def collect_lingtai_mail_results(state, payload=None):
    """Read-only collection of real LingTai agent replies from reply_inbox mailbox/inbox."""
    payload = payload or {}
    root = _lingtai_network_path()
    if not root:
        return None, "找不到 .lingtai 网络目录；请设置 LINGTAI_SIMPLE_NETWORK_DIR。"
    inbox_addr = _safe_lingtai_address(payload.get("inbox") or LINGTAI_REPLY_INBOX)
    if not inbox_addr:
        return None, "reply inbox 地址不合法"
    inbox_dir = root / inbox_addr / "mailbox" / "inbox"
    if not inbox_dir.exists():
        return {"collected": 0, "inbox": inbox_addr, "note": "reply inbox 不存在或暂无邮件"}, None
    dispatches = state.setdefault("lingtai_dispatches", [])
    known = {r.get("mailbox_id") for r in state.setdefault("lingtai_mail_results", [])}
    max_scan = int(payload.get("max_scan") or 400)
    paths = sorted(inbox_dir.glob("*/message.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:max_scan]
    collected = []
    for path in paths:
        msg = _read_lingtai_message_file(path)
        if not msg or msg["mailbox_id"] in known:
            continue
        dispatch = _match_reply_to_dispatch(msg, dispatches)
        if not dispatch:
            continue
        preview = (msg.get("message") or "").strip()[:1200]
        rec = {
            "id": new_id("ltreply"),
            "mailbox_id": msg["mailbox_id"],
            "collected_at": now_iso(),
            "received_at": msg.get("received_at"),
            "from": msg.get("from"),
            "subject": msg.get("subject"),
            "message_preview": preview,
            "file_path": msg.get("file_path"),
            "dispatch_id": dispatch.get("id"),
            "task_id": dispatch.get("task_id"),
            "agent_id": dispatch.get("agent_id"),
            "worker_request_id": dispatch.get("worker_request_id"),
            "worker_kind": dispatch.get("worker_kind"),
        }
        state["lingtai_mail_results"].insert(0, rec)
        state["lingtai_mail_results"] = state["lingtai_mail_results"][:120]
        dispatch["status"] = "reply_received"
        dispatch.setdefault("reply_mailbox_ids", []).append(msg["mailbox_id"])
        dispatch["last_reply_at"] = rec["collected_at"]
        if dispatch.get("worker_request_id"):
            wr = _worker_request_by_id(state, dispatch.get("worker_request_id"))
            if wr:
                wr["status"] = "reply_received"
                wr["reply_result_id"] = rec["id"]
                wr["reply_preview"] = preview[:500]
                wr["completed_at"] = rec["collected_at"]
                wr.setdefault("steps", []).append("controller_reply_collected")
                if wr.get("user_id") or wr.get("reply_to_message_id"):
                    _wechat_outbox_add(
                        state, inbound_id=wr.get("inbound_id") or rec["id"],
                        user_id=wr.get("user_id") or "",
                        reply_to_message_id=wr.get("reply_to_message_id") or "",
                        reply_text=(
                            f"受控 worker 调度已回收：{wr.get('id')}（{_worker_kind_label(wr.get('kind'))}）\n"
                            f"来自：{msg.get('from') or ''}\n"
                            f"摘要：{preview[:900]}"
                        ),
                    )
        if dispatch.get("task_id"):
            task = _task_by_id(state, dispatch.get("task_id"))
            if task:
                task["status"] = "完成"
                task["result"] = "真实 LingTai agent 已回复：" + preview[:500]
        if dispatch.get("agent_id"):
            ag = find_agent(state, dispatch.get("agent_id"))
            if ag:
                ag["status"] = "待命"
        collected.append(rec)
        known.add(msg["mailbox_id"])
    state.setdefault("lingtai_runtime", default_state()["lingtai_runtime"])["last_collect_at"] = now_iso()
    if collected:
        log_event(state, f"回收真实 LingTai agent 回复 {len(collected)} 条（inbox={inbox_addr}）", kind="lingtai_runtime")
    return {"collected": len(collected), "inbox": inbox_addr, "results": collected}, None


def request_lingtai_lifecycle(state, payload):
    """Create a confirmation item for real LingTai lifecycle operations."""
    action = (payload.get("action") or "").strip().lower()
    address = _safe_lingtai_address(payload.get("address") or "")
    allowed = {"lull", "suspend", "interrupt", "clear", "cpr"}
    if action not in allowed:
        return None, "当前只支持真实生命周期动作：lull/suspend/interrupt/clear/cpr；不做文件删除或 nirvana。"
    if not address:
        return None, "请提供真实 LingTai agent 地址"
    agent_dir = _lingtai_agent_dir(address)
    if not agent_dir or not (agent_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{address}"
    hb = _heartbeat_info(agent_dir)
    detail = (
        f"动作：{action}\n地址：{address}\n"
        f"当前 heartbeat：alive={hb.get('alive')} age={hb.get('age_seconds')}s\n"
        "说明：确认后会对真实 agent 生效。lull/suspend/interrupt/clear 写入对应 signal 文件；cpr 会用 lingtai-agent run 重启已停止 agent。"
    )
    ap = add_approval(state, {
        "action": "lingtai_lifecycle",
        "title": f"真实 LingTai 生命周期动作：{action} {address}",
        "detail": detail,
        "lingtai_action": action,
        "lingtai_address": address,
        "preview": detail,
    })
    return ap, None


def lingtai_lifecycle_apply_real(state, ap):
    action = (ap.get("lingtai_action") or "").strip().lower()
    address = _safe_lingtai_address(ap.get("lingtai_address") or "")
    agent_dir = _lingtai_agent_dir(address)
    if action not in {"lull", "suspend", "interrupt", "clear", "cpr"}:
        return None, "不支持的 LingTai 生命周期动作"
    if not agent_dir or not (agent_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{address}"
    hb = _heartbeat_info(agent_dir)
    if action in {"lull", "suspend", "interrupt", "clear"} and not hb.get("alive"):
        return None, f"{address} 当前没有新鲜 heartbeat；不能执行 {action}"
    if action == "lull":
        (agent_dir / ".sleep").write_text("", encoding="utf-8")
        status = "sleep_signal_written"
    elif action == "suspend":
        (agent_dir / ".suspend").write_text("", encoding="utf-8")
        status = "suspend_signal_written"
    elif action == "interrupt":
        (agent_dir / ".interrupt").write_text("", encoding="utf-8")
        status = "interrupt_signal_written"
    elif action == "clear":
        (agent_dir / ".clear").write_text("lingtai-simple", encoding="utf-8")
        status = "clear_signal_written"
    else:  # cpr
        if hb.get("alive"):
            return None, f"{address} 已有新鲜 heartbeat；不需要 CPR"
        init_path = agent_dir / "init.json"
        if not init_path.exists():
            return None, f"{address} 缺少 init.json，不能 CPR"
        if not os.path.exists(LINGTAI_AGENT_CMD):
            return None, f"找不到 lingtai-agent：{LINGTAI_AGENT_CMD}"
        proc = subprocess.Popen([LINGTAI_AGENT_CMD, "run", str(agent_dir)], cwd=str(agent_dir),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        status = f"cpr_started_pid_{proc.pid}"
    event = {
        "id": new_id("ltlife"),
        "created_at": now_iso(),
        "address": address,
        "action": action,
        "status": status,
    }
    state.setdefault("lingtai_lifecycle_events", []).insert(0, event)
    state["lingtai_lifecycle_events"] = state["lingtai_lifecycle_events"][:80]
    for ag in state.get("agents", []):
        if ag.get("lingtai_address") == address:
            if action in ("lull", "suspend"):
                ag["status"] = "已暂停"
            elif action == "cpr":
                ag["status"] = "正在干"

    log_event(state, f"真实 LingTai 生命周期动作已执行：{action} {address} ({status})", kind="lingtai_runtime")
    return event, None


_AVATAR_NAME_RE = re.compile(r"^[\w-]{1,64}$", re.UNICODE)


def _safe_avatar_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or name.startswith("."):
        return None
    if any(x in name for x in ("/", "\\", "\x00", " ")):
        return None
    if not _AVATAR_NAME_RE.match(name):
        return None
    return name


def _mission_looks_too_short(mission):
    mission = (mission or "").strip()
    if len(mission) < 12:
        return True
    lowered = mission.lower()
    return lowered in {"test", "测试", "hello", "hi", "spawn", "avatar"}


def _make_simple_avatar_init(parent_init, name, comment=""):
    """Build a shallow avatar init.json from a real parent init.json, following kernel avatar safety rules."""
    init = json.loads(json.dumps(parent_init))
    init.setdefault("manifest", {})["agent_name"] = name
    init["prompt"] = ""
    init.pop("prompt_file", None)
    init.setdefault("manifest", {})["admin"] = {}
    init["comment"] = comment or "由 LingTai Simple 创建的真实同网 avatar。"
    init.pop("comment_file", None)
    init.pop("brief", None)
    init.pop("brief_file", None)
    init.pop("addons", None)  # avoid duplicate polling of chat/email addons
    init.pop("history", None)
    init.pop("identity", None)
    init.pop("id", None)
    return init


def _write_avatar_ledger(template_dir, event):
    try:
        ledger = template_dir / "delegates" / "ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def bind_lingtai_avatar(state, payload):
    """Bind an existing real LingTai agent directory to a local Simple card (local state only)."""
    address = _safe_lingtai_address(payload.get("address") or payload.get("lingtai_address") or "")
    if not address:
        return None, "请提供要绑定的真实 LingTai agent 地址"
    agent_dir = _lingtai_agent_dir(address)
    if not agent_dir or not (agent_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{address}"
    existing = next((a for a in state.get("agents", []) if a.get("lingtai_address") == address), None)
    try:
        meta = json.loads((agent_dir / ".agent.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    hb = _heartbeat_info(agent_dir)
    name = (payload.get("name") or meta.get("nickname") or meta.get("agent_name") or address).strip()
    role = (payload.get("role") or "已绑定真实 LingTai agent").strip()
    if existing:
        existing.update({
            "name": name or existing.get("name") or address,
            "role": role,
            "status": "待命" if hb.get("alive") else "未在线",
            "lingtai_address": address,
            "context_pressure": existing.get("context_pressure", existing.get("context_base", 12)),
            "lingtai_bound_at": existing.get("lingtai_bound_at") or now_iso(),
            "lingtai_retired": False,
        })
        local_agent = existing
    else:
        if len(state.get("agents", [])) >= MAX_AGENTS:
            return None, f"本地灵卡片已达上限 {MAX_AGENTS}；请先退休/删除不需要的本地卡片。"
        local_agent = {
            "id": new_id("agent"), "name": name or address, "role": role,
            "provider_id": "", "model": "", "cc_level": 1,
            "status": "待命" if hb.get("alive") else "未在线",
            "created_at": now_iso(), "recent_tasks": [], "context_base": 12,
            "lingtai_address": address, "context_pressure": 12,
            "lingtai_bound_at": now_iso(), "lingtai_retired": False,
        }
        state.setdefault("agents", []).append(local_agent)
    event = {
        "id": new_id("ltavatar"), "created_at": now_iso(),
        "event": "bind", "name": local_agent.get("name"), "address": address,
        "local_agent_id": local_agent.get("id"), "status": "bound",
        "alive": hb.get("alive"), "heartbeat_age_seconds": hb.get("age_seconds"),
        "working_dir": str(agent_dir),
    }
    state.setdefault("lingtai_avatar_events", []).insert(0, event)
    state["lingtai_avatar_events"] = state["lingtai_avatar_events"][:80]
    log_event(state, f"已绑定真实 LingTai agent 到 Simple 卡片：{address}", kind="lingtai_runtime")
    return {"agent": local_agent, "event": event}, None


def request_lingtai_avatar_retire(state, payload):
    """Queue a safe retirement/unbind action for a real-bound Simple card. No filesystem deletion."""
    local_agent_id = payload.get("agent_id") or payload.get("local_agent_id") or ""
    local_agent = find_agent(state, local_agent_id) if local_agent_id else None
    address = _safe_lingtai_address(payload.get("address") or (local_agent or {}).get("lingtai_address") or "")
    retire_action = (payload.get("retire_action") or payload.get("action_after_retire") or "none").strip().lower()
    if retire_action not in {"none", "lull", "suspend"}:
        return None, "退休动作只支持 none/lull/suspend；不会提供删除目录或 nirvana。"
    if not address:
        return None, "请提供要退休/解绑的真实 LingTai agent 地址"
    agent_dir = _lingtai_agent_dir(address)
    if not agent_dir or not (agent_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{address}"
    hb = _heartbeat_info(agent_dir)
    note = (payload.get("note") or payload.get("handoff") or "").strip()
    detail = (
        f"地址：{address}\n本地卡片：{(local_agent or {}).get('name') or local_agent_id or '未绑定'}\n"
        f"退休后动作：{retire_action}\n当前 heartbeat：alive={hb.get('alive')} age={hb.get('age_seconds')}s\n"
        "确认后不会删除真实 agent 目录，不会 nirvana；只把 Simple 本地卡片标为已退休/解绑。"
        "若选择 lull/suspend，会额外写入 .sleep 或 .suspend signal。\n\n"
        f"交接备注：\n{note or '（无）'}"
    )
    ap = add_approval(state, {
        "action": "lingtai_avatar_retire",
        "title": f"真实 LingTai avatar 退休/解绑：{address}",
        "detail": detail,
        "lingtai_address": address,
        "local_agent_id": local_agent_id,
        "avatar_retire_action": retire_action,
        "avatar_retire_note": note,
        "preview": detail,
    })
    return ap, None


def lingtai_avatar_retire_apply_real(state, ap):
    address = _safe_lingtai_address(ap.get("lingtai_address") or "")
    retire_action = (ap.get("avatar_retire_action") or "none").strip().lower()
    local_agent_id = ap.get("local_agent_id") or ""
    note = ap.get("avatar_retire_note") or ""
    if retire_action not in {"none", "lull", "suspend"}:
        return None, "不支持的退休后动作"
    agent_dir = _lingtai_agent_dir(address)
    if not address or not agent_dir or not (agent_dir / ".agent.json").exists():
        return None, f"找不到真实 LingTai agent：{address}"
    hb = _heartbeat_info(agent_dir)
    status = "retired_local_only"
    if retire_action == "lull":
        if hb.get("alive"):
            (agent_dir / ".sleep").write_text("lingtai-simple-retire", encoding="utf-8")
            status = "retired_sleep_signal_written"
        else:
            status = "retired_no_fresh_heartbeat_no_signal"
    elif retire_action == "suspend":
        if hb.get("alive"):
            (agent_dir / ".suspend").write_text("lingtai-simple-retire", encoding="utf-8")
            status = "retired_suspend_signal_written"
        else:
            status = "retired_no_fresh_heartbeat_no_signal"
    affected = []
    for ag in state.get("agents", []):
        if (local_agent_id and ag.get("id") == local_agent_id) or ag.get("lingtai_address") == address:
            ag["status"] = "已退休"
            ag["lingtai_retired"] = True
            ag["retired_at"] = now_iso()
            ag["retire_note"] = note
            affected.append(ag.get("id"))
    event = {
        "id": new_id("ltavatar"), "created_at": now_iso(),
        "event": "retire", "address": address, "name": address,
        "status": status, "retire_action": retire_action,
        "local_agent_ids": affected, "working_dir": str(agent_dir),
        "note": redact(note),
    }
    state.setdefault("lingtai_avatar_events", []).insert(0, event)
    state["lingtai_avatar_events"] = state["lingtai_avatar_events"][:80]
    log_event(state, f"真实 LingTai avatar 已退休/解绑：{address} ({status})", kind="lingtai_runtime")
    return event, None


def request_lingtai_avatar_spawn(state, payload):
    """Create a confirmation item for real same-network LingTai avatar spawn."""
    name = _safe_avatar_name(payload.get("name") or payload.get("avatar_name") or "")
    mission = (payload.get("mission") or payload.get("description") or payload.get("reasoning") or "").strip()
    avatar_type = (payload.get("type") or "shallow").strip().lower()
    comment = (payload.get("comment") or "").strip()
    template_address = _safe_lingtai_address(payload.get("template_address") or LINGTAI_REPLY_INBOX or "")
    if not name:
        return None, "avatar 名称不合法：只能是单段名称，允许字母/数字/下划线/连字符，1-64 字符；不能含空格、点或斜杠。"
    if avatar_type != "shallow":
        return None, "v0.14 先只接入真实 shallow avatar spawn；deep clone 需要更严格的资料复制审计，暂不开放。"
    if _mission_looks_too_short(mission) and not payload.get("confirm_mission"):
        return None, "avatar mission 太短或像测试；请写清楚它要长期负责什么，并传 confirm_mission=true。"
    root = _lingtai_network_path()
    if not root:
        return None, "找不到 .lingtai 网络目录；请设置 LINGTAI_SIMPLE_NETWORK_DIR。"
    target_dir = root / name
    if target_dir.exists():
        return None, f"同名 LingTai agent 目录已存在：{name}"
    template_dir = _lingtai_agent_dir(template_address)
    if not template_dir or not (template_dir / "init.json").exists():
        return None, f"找不到可复制 init.json 的模板 agent：{template_address}"
    detail = (
        f"名称：{name}\n类型：shallow\n模板：{template_address}\n"
        f"目标目录：{target_dir}\n"
        "确认后会创建真实同网 peer agent 目录，复制并净化 init.json，写入 .prompt，"
        "然后用 lingtai-agent run 启动。不会删除任何既有 agent；不会配置 IM/微信/Telegram addon，避免重复 poller。\n\n"
        f"mission：\n{mission}"
    )
    ap = add_approval(state, {
        "action": "lingtai_avatar_spawn",
        "title": f"真实 LingTai avatar spawn：{name}",
        "detail": detail,
        "avatar_name": name,
        "avatar_type": avatar_type,
        "avatar_mission": mission,
        "avatar_comment": comment,
        "avatar_template_address": template_address,
        "preview": detail,
    })
    return ap, None


def lingtai_avatar_spawn_apply_real(state, ap):
    name = _safe_avatar_name(ap.get("avatar_name") or "")
    mission = (ap.get("avatar_mission") or "").strip()
    comment = (ap.get("avatar_comment") or "").strip()
    template_address = _safe_lingtai_address(ap.get("avatar_template_address") or LINGTAI_REPLY_INBOX or "")
    if not name or not mission:
        return None, "avatar spawn 缺少名称或 mission"
    root = _lingtai_network_path()
    if not root:
        return None, "找不到 .lingtai 网络目录"
    target_dir = root / name
    if target_dir.exists():
        return None, f"同名 LingTai agent 目录已存在：{name}"
    template_dir = _lingtai_agent_dir(template_address)
    init_path = template_dir / "init.json" if template_dir else None
    if not init_path or not init_path.exists():
        return None, f"找不到模板 init.json：{template_address}"
    if not os.path.exists(LINGTAI_AGENT_CMD):
        return None, f"找不到 lingtai-agent：{LINGTAI_AGENT_CMD}"
    try:
        parent_init = json.loads(init_path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"读取模板 init.json 失败：{e}"
    try:
        target_dir.mkdir(parents=False, exist_ok=False)
        avatar_init = _make_simple_avatar_init(parent_init, name, comment=comment)
        (target_dir / "init.json").write_text(json.dumps(avatar_init, ensure_ascii=False, indent=2), encoding="utf-8")
        first_prompt = (
            "你是由圆酱的 LingTai Simple 创建的真实同网 avatar。\n"
            f"你的名称/地址：{name}\n"
            f"父模板 agent：{template_address}\n\n"
            "你的任务：\n" + mission + "\n\n"
            "纪律：按真实能力做事；需要外部副作用时先请求确认；完成或卡住时用内部邮件回复 mimo-2-5-pro。"
        )
        (target_dir / ".prompt").write_text(first_prompt, encoding="utf-8")
        stderr_path = target_dir / "avatar_spawn.stderr.log"
        with open(stderr_path, "ab") as errf:
            proc = subprocess.Popen([LINGTAI_AGENT_CMD, "run", str(target_dir)], cwd=str(target_dir),
                                    stdout=subprocess.DEVNULL, stderr=errf, start_new_session=True)
        boot_status = "started"
        boot_error = ""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if proc.poll() is not None:
                boot_status = "failed"
                try:
                    boot_error = stderr_path.read_text(encoding="utf-8", errors="replace")[-1200:]
                except Exception:
                    boot_error = f"process exited with code {proc.returncode}"
                break
            hb = _heartbeat_info(target_dir)
            if hb.get("heartbeat"):
                boot_status = "booted" if hb.get("alive") else "started"
                break
            time.sleep(0.2)
        if boot_status == "failed":
            shutil.rmtree(target_dir, ignore_errors=True)
            return None, f"avatar 启动失败：{boot_error or 'unknown error'}"
        event = {
            "id": new_id("ltavatar"),
            "created_at": now_iso(),
            "name": name,
            "address": name,
            "template_address": template_address,
            "type": "shallow",
            "pid": proc.pid,
            "boot_status": boot_status,
            "working_dir": str(target_dir),
        }
        state.setdefault("lingtai_avatar_events", []).insert(0, event)
        state["lingtai_avatar_events"] = state["lingtai_avatar_events"][:80]
        # Bind a local Simple agent card so the new real avatar can be dispatched to immediately.
        if not any(a.get("lingtai_address") == name for a in state.get("agents", [])) and len(state.get("agents", [])) < MAX_AGENTS:
            local_agent = {
                "id": new_id("agent"), "name": name, "role": "真实 LingTai avatar",
                "provider_id": "", "model": "", "cc_level": 1, "status": "正在干" if boot_status in ("started", "booted") else "待命",
                "created_at": now_iso(), "recent_tasks": [], "context_base": 12,
                "lingtai_address": name, "context_pressure": 12,
            }
            state["agents"].append(local_agent)
            event["local_agent_id"] = local_agent["id"]
        _write_avatar_ledger(template_dir, {"ts": time.time(), "event": "lingtai_simple_avatar", "name": name,
                                           "working_dir": target_dir.name, "mission": mission,
                                           "type": "shallow", "pid": proc.pid,
                                           "boot_status": boot_status})
        log_event(state, f"真实 LingTai avatar 已创建：{name} ({boot_status}, pid={proc.pid})", kind="lingtai_runtime")
        return event, None
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        return None, f"创建 avatar 失败：{e}"


def orchestrate_multi_agent(state, payload):
    """真实本地多 agent 编排：创建/选择子灵，拆任务，记录批次；不假装外部模型已执行。"""
    objective = (payload.get("objective") or payload.get("description") or "").strip()
    if not objective:
        return None, "多 agent 目标不能为空"
    source = payload.get("source") or "ui"
    requested = payload.get("agent_ids") or []
    selected = [find_agent(state, aid) for aid in requested]
    selected = [a for a in selected if a]

    if not selected:
        templates = [
            ("主控洞察灵", "洞察 / 风险 / 下一步"),
            ("执行落地灵", "执行 / 文件 / 代码苦力"),
            ("审校回环灵", "审校 / 边界 / 收功"),
        ]
        for name, role in templates:
            if len(state.get("agents", [])) >= MAX_AGENTS:
                break
            existing = next((a for a in state.get("agents", []) if a.get("name") == name), None)
            if existing:
                selected.append(existing)
            else:
                a, err = create_agent(state, {"name": name, "role": role, "cc_level": 1})
                if a:
                    selected.append(a)
        if not selected and state.get("agents"):
            selected = state["agents"][:3]
    if not selected:
        return None, "无法创建或选择子灵"

    step_templates = [
        "洞察：先判断目标、风险、边界和需要确认的动作。",
        "执行：把目标拆成可落地的小步骤，优先做能真实验证的一步。",
        "审校：检查是否有 mock 冒充、凭证泄露、外部副作用和未说明边界。",
        "回环：汇总结果、下一步和需要沉淀到 skill/knowledge/pad 的内容。",
    ]
    tasks = []
    for i, agent in enumerate(selected):
        desc = f"多 agent 编排｜目标：{objective}\n子任务：{step_templates[i % len(step_templates)]}"
        risk = "sensitive" if any(k in objective for k in ("push", "PR", "merge", "提交", "合并", "删除", "回滚", "rollback")) else "low"
        task, err = assign_task(state, {"agent_id": agent["id"], "description": desc, "source": source, "risk": risk, "action_type": "multi_agent_sensitive" if risk == "sensitive" else "multi_agent_task"})
        if task:
            tasks.append(task)
    batch = {
        "id": new_id("orch"),
        "created_at": now_iso(),
        "objective": redact(objective),
        "source": source,
        "agent_ids": [a["id"] for a in selected],
        "agent_names": [a["name"] for a in selected],
        "task_ids": [t["id"] for t in tasks],
        "status": "等确认" if any(t.get("status") == "等确认" for t in tasks) else "已编排",
        "summary": f"已把目标拆给 {len(selected)} 个子灵：" + "、".join(a["name"] for a in selected),
    }
    state.setdefault("orchestrations", []).insert(0, batch)
    state["orchestrations"] = state["orchestrations"][:50]
    insight, _ = generate_insights(state, {"focus": objective})
    batch["insight_id"] = insight["id"]
    log_event(state, f"多 agent 编排：{objective[:50]}", kind="multi_agent")
    return batch, None


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
        # 绑定真实 LingTai agent 的本地卡片不是普通缓存：删除按钮改为“退休/解绑”确认闸，绝不删除真实目录。
        if agent.get("lingtai_address"):
            ap, err = request_lingtai_avatar_retire(state, {
                "agent_id": agent_id,
                "address": agent.get("lingtai_address"),
                "retire_action": "none",
                "note": "从 Simple 本地卡片删除入口触发：只退休/解绑，不删除真实 agent 目录。",
            })
            if err:
                return None, err
            return {"queued_approval": ap["id"], "mode": "retire_not_delete"}, None
        # 未绑定真实地址的本地轻量卡片仍可按本地状态删除。
        ap = add_approval(state, {
            "action": "delete_agent",
            "title": f"删除本地灵卡片：{agent['name']}",
            "detail": f"将只删除 Simple 本地灵卡片 {agent['name']}（{agent['id']}）。不会删除任何真实 LingTai agent 目录。",
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
    for k in ("rollback_ref", "rollback_commit", "snapshot_id", "commit_message", "commit_safety_ref", "github_repo", "github_base_branch", "github_head_branch", "github_head_commit", "github_pr_title", "github_pr_body", "github_pr_number", "github_pr_url", "github_merge_method", "lingtai_action", "lingtai_address", "avatar_name", "avatar_type", "avatar_mission", "avatar_comment", "avatar_template_address", "avatar_retire_action", "avatar_retire_note", "local_agent_id", "cost_kind", "cost_provider_id", "cost_task_id", "cost_estimated_usd", "cost_cap_usd", "cost_reason", "worker_request_id", "worker_kind", "worker_controller", "worker_description", "worker_route_id", "worker_inbound_id", "worker_user_id", "worker_reply_to_message_id"):
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
        "lingtai_lifecycle": f"[真实 LingTai 生命周期动作预览 / 确认后会写入 .sleep/.suspend/.interrupt/.clear signal 或执行 CPR]\n{detail}",
        "lingtai_avatar_spawn": f"[真实 LingTai avatar spawn 预览 / 确认后会创建同网 peer agent 目录、写 init.json/.prompt，并启动 lingtai-agent run]\n{detail}",
        "lingtai_avatar_retire": f"[真实 LingTai avatar 退休/解绑预览 / 确认后不会删除目录；只做本地退休记录，并可选择写入 sleep/suspend signal]\n{detail}",
        "delete_agent": f"[删除灵预览]\n{detail}",
        "high_cost_api": f"[高成本 API 预览 / 不会真实调用]\n{detail}",
        "budget_override": f"[预算/成本越线预览 / 确认后给该类动作一次短时放行；不会自动发起外部调用]\n{detail}",
        "worker_dispatch": f"[受控 worker 调度预览 / 确认后会写入真实 LingTai 内部邮箱，请主控 agent 执行 daemon/Codex/Claude/avatar 类工作并回信；不启动第二微信 poller，不绕过确认闸]\n{detail}",
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
    if action == "lingtai_lifecycle":
        result, err = lingtai_lifecycle_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        return None
    if action == "lingtai_avatar_spawn":
        result, err = lingtai_avatar_spawn_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        return None
    if action == "lingtai_avatar_retire":
        result, err = lingtai_avatar_retire_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        return None
    if action == "worker_dispatch":
        result, err = worker_request_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        return None
    if action == "budget_override":
        result, err = budget_override_apply_real(state, ap)
        if err:
            return err
        ap["result"] = result
        return None
    if action == "delete_agent" and ap.get("agent_id"):
        state["agents"] = [a for a in state["agents"] if a["id"] != ap["agent_id"]]
        log_event(state, "（本地状态）已删除灵")
    if ap.get("task_id"):
        for t in state["tasks"]:
            if t["id"] == ap["task_id"]:
                t["status"] = "完成"
                if action in ("wechat_send", "email_send", "telegram_send", "sensitive_task"):
                    t["result"] = f"已确认：{action}；当前 v0.21 对该通用动作仅完成本地确认/记录；已有专门执行器的 rollback、code_commit、code_pr、code_merge 会走真实执行路径。"
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
    """保存供应商配置。若带 api_key，则 Keychain-first；显式允许时才写受限 .secrets fallback。"""
    provider_id = payload.get("provider_id")
    catalog = {p["id"]: p for p in PROVIDER_CATALOG}
    if provider_id not in catalog:
        return None, "未知供应商"
    raw_key = (payload.get("api_key") or "").strip()   # 仅用于写安全存储 + 取后四位，绝不存进 state
    allow_fallback = bool(payload.get("allow_secret_fallback"))
    base_url = (payload.get("base_url") or catalog[provider_id]["default_base_url"]).strip()
    model = (payload.get("model") or "").strip()

    existing = _provider_entry(state, provider_id) or {}
    status = provider_secret_status(provider_id)
    key_last4_val = existing.get("key_last4")
    key_source = status.get("key_source")

    if raw_key:
        stored = False
        keychain_error = None
        if keychain_available():
            try:
                keychain_set(provider_id, raw_key)
                stored = True
                key_source = "keychain"
            except KeychainUnavailable as e:
                keychain_error = str(e)
        else:
            keychain_error = "Keychain 不可用"
        if not stored:
            if not allow_fallback:
                return None, (
                    "无法保存 key 到 Keychain：" + (keychain_error or "未知错误") +
                    "。为防止明文泄露，默认拒绝落盘；如你明确接受受限 fallback，请勾选 allow_secret_fallback，"
                    "系统会写入 .secrets/providers/<provider>.key 并强制 0700/0600 权限。"
                )
            try:
                secret_fallback_set(provider_id, raw_key)
                key_source = "secret_file"
                stored = True
            except KeychainUnavailable as e:
                return None, str(e)
        key_last4_val = key_last4(raw_key)

    status = provider_secret_status(provider_id)
    if key_source:
        # provider_secret_status is authoritative after writes, but env may appear before file if both exist.
        key_source = status.get("key_source") or key_source
    else:
        key_source = status.get("key_source")
    in_keychain = bool(status.get("in_keychain"))
    secret_file_present = bool(status.get("secret_file_present"))
    env_slot_present = bool(status.get("env_slot_present"))
    configured = bool(key_source)

    entry = {
        "provider_id": provider_id,
        "name": catalog[provider_id]["name"],
        "base_url": base_url,
        "model": model,
        "tags": catalog[provider_id]["tags"],
        "configured": configured,
        "in_keychain": in_keychain,
        "key_source": key_source,
        "secret_file_present": secret_file_present,
        "env_slot_present": env_slot_present,
        "env_slot": status.get("env_slot"),
        "key_label": payload.get("key_label") or existing.get("key_label") or None,
        "key_last4": key_last4_val if configured else None,
        "updated_at": now_iso(),
    }
    entry.pop("api_key", None)
    state["providers"] = [p for p in state["providers"] if p["provider_id"] != provider_id]
    state["providers"].append(entry)
    log_event(state, f"保存供应商配置：{entry['name']}（key_source={key_source or 'none'}）")
    return entry, None


def delete_provider_key(state, payload):
    """删除本服务可管理的 key：Keychain + .secrets fallback。env slot 只提示，不能删除。"""
    provider_id = payload.get("provider_id")
    if provider_id not in PROVIDER_IDS:
        return None, "未知供应商"
    deleted_keychain = False
    if keychain_available():
        try:
            deleted_keychain = bool(keychain_delete(provider_id))
        except Exception:
            deleted_keychain = False
    deleted_secret_file = secret_fallback_delete(provider_id)
    status = provider_secret_status(provider_id)
    entry = _provider_entry(state, provider_id)
    if entry:
        entry["in_keychain"] = bool(status.get("in_keychain"))
        entry["secret_file_present"] = bool(status.get("secret_file_present"))
        entry["env_slot_present"] = bool(status.get("env_slot_present"))
        entry["key_source"] = status.get("key_source")
        entry["configured"] = bool(status.get("configured"))
        if not entry["configured"]:
            entry["key_last4"] = None
        entry["updated_at"] = now_iso()
    log_event(state, f"已删除 provider key（Keychain/.secrets 可管理部分）：{provider_id}")
    return {"provider_id": provider_id, "deleted_keychain": deleted_keychain,
            "deleted_secret_file": deleted_secret_file, **status}, None


def check_provider_key(state, payload):
    """检查 Keychain/env/.secrets 是否存在该供应商 key（不读出/回显明文）。同步修正 state 标记。"""
    provider_id = payload.get("provider_id")
    if provider_id not in PROVIDER_IDS:
        return None, "未知供应商"
    status = provider_secret_status(provider_id)
    entry = _provider_entry(state, provider_id)
    if entry:
        entry["in_keychain"] = bool(status.get("in_keychain"))
        entry["secret_file_present"] = bool(status.get("secret_file_present"))
        entry["env_slot_present"] = bool(status.get("env_slot_present"))
        entry["env_slot"] = status.get("env_slot")
        entry["key_source"] = status.get("key_source")
        entry["configured"] = bool(status.get("configured"))
        if not entry["configured"]:
            entry["key_last4"] = None
    if not status.get("keychain_available"):
        status["note"] = "本机无法加载 macOS Security.framework；可使用只读 env slot 或显式受限 .secrets fallback。"
    return {"provider_id": provider_id, **status}, None


def prepare_model_test(state, payload):
    """
    真实模型调用的「锁内准备」阶段：校验 + Keychain-first/env/.secrets 取 key + 解析 base_url/model。
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

    api_key, key_source = resolve_provider_api_key(provider_id)
    if not api_key:
        env_name = _provider_env_key_name(provider_id)
        return None, ("未找到该供应商 key：请先保存到 Keychain；或设置只读 env slot " + env_name +
                      "；或在模型/API中心显式启用受限 .secrets fallback。")

    pre_estimate, pre_usage = estimate_model_cost_usd(state, provider_id, usage=None, prompt=prompt, max_tokens=MODEL_CALL_MAX_TOKENS)
    budget_err = budget_preflight(state, kind="model_call", provider_id=provider_id,
                                  estimated_usd=pre_estimate, note=f"model={model}; key_source={key_source}")
    if budget_err:
        return None, budget_err

    log_event(state, f"真实模型调用（可能计费）：{provider_id} / {model} / key_source={key_source} / 预估≈${pre_estimate:.6f}", kind="real_api")
    return {"provider_id": provider_id, "base_url": base_url, "model": model,
            "prompt": prompt, "api_key": api_key, "key_source": key_source,
            "preflight_estimated_cost_usd": pre_estimate, "preflight_usage_estimate": pre_usage}, None


# --------------------------------------------------------------------------
# Unified Task Router / WeChat runner contract (v0.21)
# --------------------------------------------------------------------------

def _first_available_agent(state, *, fallback_name="微信主控灵", fallback_role="长期助手", lingtai_address=""):
    for a in state.get("agents", []):
        if a.get("status") in ("待命", "正在干"):
            if lingtai_address and not a.get("lingtai_address"):
                a["lingtai_address"] = lingtai_address
            return a
    agent, _ = create_agent(state, {
        "name": fallback_name,
        "role": fallback_role,
        "provider_id": "",
        "model": "",
        "cc_level": 1,
        "lingtai_address": lingtai_address,
    })
    return agent


def _parse_dispatch_command(text):
    """Parse: 派发 <address> <message> / 派给 <address> <message> / dispatch <address> <message>."""
    stripped = (text or "").strip()
    for prefix in ("派发 ", "派给 ", "dispatch ", "mailbox "):
        if stripped.lower().startswith(prefix.strip().lower() + " "):
            rest = stripped[len(prefix):].strip()
            parts = rest.split(maxsplit=1)
            if len(parts) == 2 and _safe_lingtai_address(parts[0]):
                return parts[0], parts[1]
    return "", stripped


def _classify_route(text, payload=None):
    payload = payload or {}
    forced = (payload.get("route") or payload.get("route_type") or "").strip().lower()
    if forced:
        return forced
    lower = (text or "").strip().lower()
    if lower in ("洞察", "insight", "/insight") or lower.startswith(("洞察 ", "insight ")):
        return "insight"
    if lower in ("心流", "soul", "/soul") or lower.startswith(("心流 ", "soul ")):
        return "soul"
    if lower.startswith(("收功", "shougong", "/shougong")):
        return "shougong"
    if lower.startswith(("多agent ", "多 agent ", "multiagent ", "multi-agent ")):
        return "multi_agent"
    if lower in ("回收", "collect", "收回信", "回收结果") or "回收" in lower and "回复" in lower:
        return "collect_lingtai"
    if payload.get("address") or payload.get("confirm_dispatch") or _parse_dispatch_command(text)[0]:
        return "lingtai_mailbox"
    if any(k in lower for k in ("claude", "codex", "改代码", "代码", "commit", "pr", "merge")):
        return "code_worker"
    if any(k in lower for k in ("daemon", "分神", "临时分析", "扫一遍")):
        return "daemon_plan"
    return "local_task"


def _record_router_run(state, route):
    state.setdefault("router_runs", []).insert(0, route)
    state["router_runs"] = state["router_runs"][:100]
    state.setdefault("wechat_bridge", default_state()["wechat_bridge"])["last_route_at"] = route.get("created_at")
    log_event(state, f"统一 Task Router：{route.get('route_type')} / {route.get('status')} / {route.get('text','')[:40]}", kind="task_router")
    return route


def _router_reply(route):
    rt = route.get("route_type")
    status = route.get("status")
    if route.get("reply_text"):
        return route["reply_text"]
    if rt == "lingtai_mailbox" and status == "dispatched":
        return f"收到，已通过统一 Task Router 派发到真实 LingTai 内部邮箱：{route.get('dispatch_id')}。我会继续用回收入口收结果。"
    if rt == "lingtai_mailbox" and status == "needs_confirm_dispatch":
        return "收到，已识别为真实 LingTai agent 派发任务；为避免误唤醒/占用真实 agent，需要确认 dispatch 后再写内部邮箱。"
    if rt == "code_worker":
        return "收到，已识别为代码苦力任务；L1/L2 会产生外部模型调用或改动本仓库，请走 Claude Code 按钮/API 并显式确认费用/改动；L3-L5 会进入确认队列。"
    if rt == "daemon_plan":
        return "收到，已识别为临时分神/daemon 类任务；当前 Simple 记录了路由计划，真正启动 daemon 仍由当前 LingTai 主控执行，避免本地服务越权起分神。"
    return f"收到，已通过统一 Task Router 处理：{rt}（{status}）。"


def route_task(state, payload):
    """
    Unified Task Router: one sentence -> local task / multi-agent / insight / soul / shougong /
    real LingTai mailbox dispatch / Claude-Code handoff plan.

    This function never stores secrets and never bypasses Approval Queue.  Real LingTai mailbox
    dispatch only happens when confirm_dispatch=true or an explicit bridge caller already confirmed.
    """
    text = (payload.get("text") or payload.get("description") or payload.get("message") or "").strip()
    if not text:
        return None, "Task Router 内容不能为空"
    source = payload.get("source") or "ui"
    route_type = _classify_route(text, payload)
    route = {
        "id": new_id("route"),
        "created_at": now_iso(),
        "source": source,
        "text": redact(text),
        "route_type": route_type,
        "status": "started",
        "steps": ["received", f"classified:{route_type}"],
        "outputs": [],
    }

    if route_type == "insight":
        focus = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        ins, err = generate_insights(state, {"focus": focus})
        if err:
            return None, err
        route.update({"status": "completed", "insight_id": ins["id"], "reply_text": f"洞察 {ins['id']}：{ins.get('summary','')}"})
        route["steps"].append("insight_generated")
        return _record_router_run(state, route), None

    if route_type == "soul":
        trigger = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else source
        flow, err = generate_soul_flow(state, {"trigger": trigger})
        if err:
            return None, err
        route.update({"status": "completed", "soul_flow_id": flow["id"], "reply_text": flow["text"]})
        route["steps"].append("soul_flow_generated")
        return _record_router_run(state, route), None

    if route_type == "shougong":
        sg = generate_shougong(state)
        route.update({"status": "completed", "shougong_path": sg["path"], "reply_text": f"已生成收功单：{sg['path']}"})
        route["steps"].append("shougong_generated")
        return _record_router_run(state, route), None

    if route_type == "multi_agent":
        objective = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else text
        batch, err = orchestrate_multi_agent(state, {"objective": objective, "source": source})
        if err:
            return None, err
        route.update({"status": "completed", "orchestration_id": batch["id"], "task_ids": batch.get("task_ids", []),
                      "reply_text": f"{batch['summary']}\n批次：{batch['id']}\n任务：{', '.join(batch.get('task_ids', [])[:5])}"})
        route["steps"].append("multi_agent_orchestrated")
        return _record_router_run(state, route), None

    if route_type == "collect_lingtai":
        coll, err = collect_lingtai_mail_results(state, payload)
        if err:
            return None, err
        route.update({"status": "completed", "collected": coll.get("collected", 0),
                      "reply_text": f"已回收真实 LingTai agent 回复：{coll.get('collected',0)} 条。"})
        route["steps"].append("lingtai_replies_collected")
        return _record_router_run(state, route), None

    if route_type == "lingtai_mailbox":
        cmd_addr, cmd_body = _parse_dispatch_command(text)
        address = _safe_lingtai_address(payload.get("address") or cmd_addr or "")
        body = (payload.get("message") or cmd_body or text).strip()
        if not address:
            route.update({"status": "needs_address", "reply_text": "已识别为真实 LingTai mailbox 派发，但缺少 agent 地址。用法：派发 <agent地址> <任务内容>。"})
            return _record_router_run(state, route), None
        agent = _first_available_agent(state, fallback_name=f"真实灵：{address}", fallback_role="长期助手", lingtai_address=address)
        task, err = assign_task(state, {"agent_id": agent["id"], "description": body, "source": source, "risk": "low"})
        if err:
            return None, err
        route["task_id"] = task["id"]
        route["agent_id"] = agent["id"]
        route["steps"].append("local_task_created")
        if not payload.get("confirm_dispatch"):
            task["status"] = "等待派发确认"
            route.update({"status": "needs_confirm_dispatch", "reply_text": f"已准备派发给 {address}，本地任务 {task['id']} 已创建；真正写入 LingTai 内部邮箱需 confirm_dispatch=true。"})
            return _record_router_run(state, route), None
        dispatch, err = dispatch_task_to_lingtai(state, {"task_id": task["id"], "address": address, "message": body, "confirm_dispatch": True})
        if err:
            return None, err
        route.update({"status": "dispatched", "dispatch_id": dispatch["id"], "mailbox_id": dispatch.get("mailbox_id"),
                      "reply_text": f"已派发到真实 LingTai 内部邮箱：{address} / {dispatch.get('mailbox_id')}。可稍后发“回收”收取回复。"})
        route["steps"].append("queued_to_lingtai_mailbox")
        return _record_router_run(state, route), None

    if route_type in ("code_worker", "daemon_plan"):
        wr, err = create_controlled_worker_request(state, {
            "text": text,
            "source": source,
            "route_type": route_type,
            "route_id": route["id"],
            "level": payload.get("level"),
            "worker_kind": payload.get("worker_kind"),
            "controller": payload.get("controller"),
            "inbound_id": payload.get("inbound_id"),
            "user_id": payload.get("user_id"),
            "reply_to_message_id": payload.get("reply_to_message_id") or payload.get("message_id"),
        })
        if err:
            return None, err
        route.update({
            "status": "awaiting_worker_dispatch_approval",
            "worker_request_id": wr["id"],
            "worker_kind": wr.get("kind"),
            "task_id": wr.get("task_id"),
            "agent_id": wr.get("agent_id"),
            "approval_id": wr.get("approval_id"),
            "reply_text": (
                f"已创建受控 worker 调度请求：{wr['id']}（{wr.get('label')}）。\n"
                f"本地任务：{wr.get('task_id')}；确认项：{wr.get('approval_id')}。\n"
                f"确认后才会写入真实 LingTai 内部邮箱给 {wr.get('controller')}，由主控 agent 执行并回信；不会启动第二微信 poller。"
            ),
        })
        route["steps"].append("worker_dispatch_approval_created")
        return _record_router_run(state, route), None

    # Default: ordinary local task.
    agent = _first_available_agent(state)
    sensitive = any(k in text for k in ("发", "提交", "commit", "merge", "PR", "pr", "回滚", "rollback", "删除", "push"))
    task, err = assign_task(state, {
        "agent_id": agent["id"],
        "description": text,
        "source": source,
        "risk": "sensitive" if sensitive else "low",
        "action_type": "sensitive_task" if sensitive else "local_task",
    })
    if err:
        return None, err
    route.update({"status": task.get("status", "completed"), "task_id": task["id"], "agent_id": agent["id"],
                  "reply_text": (f"收到，已进入确认队列：{task.get('approval_id')}。" if task.get("approval_id") else f"收到，已记录到 {agent['name']} 的任务队列：{task['id']}。")})
    route["steps"].append("local_task_recorded")
    return _record_router_run(state, route), None


def wechat_bridge_pending(state, payload=None):
    """Return pending WeChat outbox items for the current LingTai MCP bridge to send; no poller, no credentials."""
    payload = payload or {}
    limit = int(payload.get("limit") or 20)
    pending = [x for x in state.get("wechat_outbox", []) if x.get("status") == "ready_for_bridge"][:limit]
    return {"pending": pending, "count": len(pending), "runner_contract": state.get("wechat_bridge", {}).get("runner_contract", "no_second_poller")}, None

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
        "ack": "已收到 ✅（本地测试入口，不会直接发真实微信）",
        "stages": ["已收到", "排队中"],
        "status": "排队中",
        "assignee": target["name"] if target else "(待派给主控)",
        "result": None,
    }
    state["wechat_inbox"].insert(0, item)
    log_event(state, f"微信任务进入队列：{text[:30]}", kind="wechat")

    if target:
        # 本地派一个 task（真实落盘记录；不直接外发微信）
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
            item["result"] = "已处理本地测试任务；真实微信外发由 WeChat MCP 桥接者原路发送。"
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
        "圆酱，LingTai Simple v0.21 当前状态：",
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
    elif lower in ("洞察", "insight", "/insight", "看洞察") or lower.startswith(("洞察 ", "insight ")):
        focus = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        ins, err = generate_insights(state, {"focus": focus})
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("洞察已生成" if not err else "洞察失败")
        if err:
            reply = f"洞察失败：{err}"
        else:
            lines = [f"洞察 {ins['id']}：{ins.get('summary','')}"]
            for f in ins.get("findings", [])[:5]:
                lines.append(f"- [{f.get('level')}] {f.get('title')}｜证据：{f.get('evidence')}｜下一步：{f.get('next_action')}")
            reply = "\n".join(lines)
    elif lower in ("心流", "soul", "/soul", "心流一下") or lower.startswith(("心流 ", "soul ")):
        trigger = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else "wechat"
        flow, err = generate_soul_flow(state, {"trigger": trigger})
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("心流已生成" if not err else "心流失败")
        reply = flow["text"] if not err else f"心流失败：{err}"
    elif lower.startswith(("多agent ", "多 agent ", "multiagent ", "multi-agent ")):
        objective = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        batch, err = orchestrate_multi_agent(state, {"objective": objective, "source": "wechat_bridge"})
        item["status"] = "完成" if not err else "卡住"
        item["stages"].append("多 agent 编排已生成" if not err else "多 agent 编排失败")
        if err:
            reply = f"多 agent 编排失败：{err}"
        else:
            reply = f"{batch['summary']}\n批次：{batch['id']}\n任务：{', '.join(batch['task_ids'][:5])}\n我也同步生成了一条洞察：{batch.get('insight_id')}"
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
        # 默认入口统一交给 v0.21 Task Router：一句话 -> 分类 -> 本地任务/真实 mailbox/代码苦力计划/回收等。
        routed, err = route_task(state, {
            "text": text, "source": "wechat_bridge",
            "confirm_dispatch": bool(payload.get("confirm_dispatch")),
            "address": payload.get("address") or "",
            "inbound_id": inbound_id, "user_id": user_id, "message_id": message_id,
        })
        if err:
            item["status"] = "卡住"
            item["stages"].append("Task Router 失败")
            reply = f"收到，但 Task Router 处理失败：{err}"
        else:
            item["status"] = routed.get("status", "完成")
            if routed.get("task_id"):
                item["task_id"] = routed.get("task_id")
            item["route_id"] = routed.get("id")
            item["stages"].extend(routed.get("steps", [])[2:] or ["Task Router 已处理"])
            reply = _router_reply(routed)

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
    lines.append("> 圆酱专属轻量版灵台 v0.21（本地原型 / Keychain、模型 API、git Time Machine、微信桥接入口、Claude Code L1-L5、多 agent 本地编排、洞察、心流、真实 LingTai 内部邮箱派发、回复回收、生命周期、avatar spawn/绑定/退休已接入）")
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
    lines.append("- 本服务不直接持有微信凭证、不启动第二个 poller；真实微信外发由当前 LingTai WeChat MCP 桥接。Time Machine / rollback、Claude Code L2 本地改码、L3 commit、L4 PR、L5 merge 已真实接入，但只能按各自边界作用，不能撤回外部副作用。")
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
        f"- Created by Yuanjiang LingTai Simple v0.21 after explicit confirmation.",
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
    reserved = _money(_float(CC_MAX_BUDGET_USD, DEFAULT_CC_RUN_CAP_USD))
    budget_err = budget_preflight(
        state, kind="claude_code_L1", estimated_usd=reserved,
        note=f"Claude Code L1 read-only run; max-budget-usd={reserved:.4f}")
    if budget_err:
        return None, None, budget_err
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
        "reserved_cost_usd": reserved,
        "cost_recorded": False,
        "cost_source": "max_budget_reservation",
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
    reserved = _money(_float(CC_MAX_BUDGET_USD, DEFAULT_CC_RUN_CAP_USD))
    budget_err = budget_preflight(
        state, kind="claude_code_L2", estimated_usd=reserved,
        note=f"Claude Code L2 local-edit run; max-budget-usd={reserved:.4f}")
    if budget_err:
        return None, None, budget_err
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
        "reserved_cost_usd": reserved,
        "cost_recorded": False,
        "cost_source": "max_budget_reservation",
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
    """Claude Code 苦力卡：v0.21 真实接入 L1/L2/L3/L4/L5；所有高危动作走确认闸。"""
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
    demo["meta"]["name"] = "圆酱专属轻量版灵台 / LingTai Simple v0.21（示例模式）"
    demo["meta"]["loaded_demo_at"] = now_iso()
    demo.setdefault("log", [])
    log_event(demo, "加载示例数据：圆酱专属灵台 v0.21 demo")
    save_state(demo)
    return {"loaded_demo": True, "agents": len(demo.get("agents", []))}, None



# --------------------------------------------------------------------------
# LingTai durable-store read-only index (pad / knowledge / skills)
# --------------------------------------------------------------------------

def _agent_root_path():
    return Path(LINGTAI_AGENT_DIR).resolve() if LINGTAI_AGENT_DIR else None


def _network_root_path():
    return Path(LINGTAI_NETWORK_DIR).resolve() if LINGTAI_NETWORK_DIR else None


def _file_info(path):
    try:
        st = path.stat()
        return {"path": str(path), "size": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")}
    except OSError:
        return {"path": str(path), "size": 0, "mtime": ""}


def _frontmatter_summary(path):
    name = path.parent.name
    desc = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return name, desc
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end].splitlines()
            current = None
            desc_lines = []
            for raw in fm:
                line = raw.rstrip()
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"\'') or name
                    current = "name"
                elif line.startswith("description:"):
                    val = line.split(":", 1)[1].strip().strip('"\'')
                    if val and val not in ("|", ">", "|-", ">-"):
                        desc_lines.append(val)
                    current = "description"
                elif current == "description" and (line.startswith(" ") or line.startswith("\t")):
                    stripped = line.strip()
                    if stripped and stripped not in ("|", ">", "|-", ">-"):
                        desc_lines.append(stripped)
                elif line and not line.startswith((" ", "\t")):
                    current = None
            desc = " ".join(desc_lines).strip()[:500]
    else:
        for line in text.splitlines():
            if line.strip().startswith("#"):
                name = line.strip("# ").strip() or name
                break
    return name, desc


def _collect_skill_items(root, source, max_items=80):
    items = []
    if not root or not root.exists():
        return items
    for path in sorted(root.rglob("SKILL.md"))[:max_items]:
        name, desc = _frontmatter_summary(path)
        info = _file_info(path)
        items.append({"name": name, "description": desc, "source": source, **info})
    return items


def scan_lingtai_memory():
    """Read-only index of the real agent's durable stores; never reads secrets or mailbox contents."""
    agent = _agent_root_path()
    network = _network_root_path()
    if not agent or not agent.exists():
        return {"ok": False, "error": "未找到真实 LingTai agent 目录", "agent_dir": LINGTAI_AGENT_DIR}
    result = {
        "ok": True,
        "scanned_at": now_iso(),
        "agent_dir": str(agent),
        "network_dir": str(network) if network else "",
        "pad": [],
        "knowledge": [],
        "skills": [],
        "summaries": [],
        "status": [],
        "boundaries": [
            "read-only index only",
            "does not read .secrets, mailbox contents, logs, or arbitrary files",
            "file reading endpoint is restricted to pad/lingtai/summaries/knowledge/custom skills/shared skills",
        ],
    }
    for rel in ("system/pad.md", "system/lingtai.md", "CURRENT_PROJECTS.md"):
        p = agent / rel
        if p.is_file():
            result["pad"].append({"name": rel, **_file_info(p)})
    for rel in (".agent.json", ".status.json"):
        p = agent / rel
        if p.is_file():
            result["status"].append({"name": rel, **_file_info(p)})
    kroot = agent / "knowledge"
    if kroot.exists():
        for p in sorted(kroot.glob("*/KNOWLEDGE.md"))[:80]:
            name, desc = _frontmatter_summary(p)
            result["knowledge"].append({"name": name, "description": desc, **_file_info(p)})
    sroot = agent / "system" / "summaries"
    if sroot.exists():
        summaries = sorted(sroot.glob("molt_*.md"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)[:12]
        result["summaries"] = [{"name": p.name, **_file_info(p)} for p in summaries]
    result["skills"].extend(_collect_skill_items(agent / ".library" / "custom", "agent_custom"))
    if network:
        result["skills"].extend(_collect_skill_items(network / ".library_shared", "network_shared"))
    result["counts"] = {k: len(result.get(k, [])) for k in ("pad", "knowledge", "skills", "summaries", "status")}
    return result


def _allowed_memory_roots():
    agent = _agent_root_path()
    network = _network_root_path()
    roots = []
    if agent:
        roots.extend([
            agent / "system" / "pad.md",
            agent / "system" / "lingtai.md",
            agent / "system" / "summaries",
            agent / "knowledge",
            agent / ".library" / "custom",
            agent / "CURRENT_PROJECTS.md",
        ])
    if network:
        roots.append(network / ".library_shared")
    return [r.resolve() for r in roots if r.exists()]


def _path_under(child, root):
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def read_lingtai_memory_file(state, payload):
    raw = (payload.get("path") or "").strip()
    if not raw:
        return None, "缺少 path。"
    path = Path(raw).expanduser().resolve()
    roots = _allowed_memory_roots()
    if not any(path == root or (root.is_dir() and _path_under(path, root)) for root in roots):
        return None, "该路径不在允许的只读记忆/技能目录中。"
    if not path.is_file():
        return None, "文件不存在。"
    if path.name.startswith("."):
        return None, "拒绝读取隐藏/敏感文件。"
    if path.suffix.lower() not in (".md", ".json", ".jsonl", ".txt"):
        return None, "只允许读取文本型记忆/技能文件。"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return None, f"读取失败：{e}"
    max_chars = max(1000, min(20000, int(payload.get("max_chars") or 6000)))
    truncated = len(text) > max_chars
    return {"path": str(path), "content": text[:max_chars], "truncated": truncated, "size": len(text)}, None


def record_lingtai_memory_scan(state, payload=None):
    scan = scan_lingtai_memory()
    if scan.get("ok"):
        state.setdefault("lingtai_memory_scans", []).insert(0, {
            "scanned_at": scan.get("scanned_at"),
            "agent_dir": scan.get("agent_dir"),
            "network_dir": scan.get("network_dir"),
            "counts": scan.get("counts", {}),
        })
        state["lingtai_memory_scans"] = state["lingtai_memory_scans"][:20]
        log_event(state, "已刷新真实 LingTai pad/knowledge/skill 只读索引。", kind="lingtai")
    return scan, None if scan.get("ok") else scan.get("error")


# --------------------------------------------------------------------------
# 架构验收矩阵：把 ARCHITECTURE_EXPERT_DISCUSSION.md 的要求变成可查询状态
# --------------------------------------------------------------------------
ARCHITECTURE_ACCEPTANCE_ITEMS = [
    {
        "id": "A01",
        "module": "WeChat Gate",
        "requirement": "接收圆酱微信消息，分类普通任务/子灵任务/确认/取消暂停收功，自动 ACK，并原路返回结果；子 agent 不得绕过主控外发。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:86-99",
        "status": "partial",
        "evidence": "已实现 /api/wechat/bridge/incoming、/api/wechat/bridge/mark_sent 与 /api/wechat/submit；真实收发由现有 LingTai WeChat MCP 作为唯一桥接者完成，避免第二 poller。",
        "gap": "尚未提供独立常驻 bridge runner；自动 ACK 阶段状态仍以 bridge 返回文本/本地状态为主。",
        "test": "python3 scripts/self_check.py（覆盖 bridge incoming/mark_sent 路径）；人工桥接需由当前 LingTai WeChat MCP 调用。",
    },
    {
        "id": "A02",
        "module": "Simple Frontend",
        "requirement": "本地傻瓜界面：最多 5 灵状态卡，新建/暂停/删除/改任务，任务队列、context 压力、API/成本、收功、Time Machine、确认队列。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:101-113",
        "status": "done",
        "evidence": "static/index.html + app.js 已提供大按钮、状态卡、任务停车场、context 压力、模型/API、预算/成本面板、确认队列、收功、Rollback、LingTai runtime 与记忆/技能索引。",
        "gap": "不是完整开发者调试台；这是 v0 的有意边界。",
        "test": "python3 scripts/self_check.py；node --check static/app.js；浏览器打开 http://127.0.0.1:8765/。",
    },
    {
        "id": "A03",
        "module": "Task Router / Orchestrator",
        "requirement": "把一句话变成任务，决定主控/长期子灵/临时分神/Claude Code，收集多 agent 结果，管理停车场、摘要与续接入口。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:115-128",
        "status": "partial",
        "evidence": "已有 /api/task/assign、/api/agent/orchestrate、洞察、心流、收功、LingTai mailbox dispatch/collect；敏感任务进入 Approval Queue。",
        "gap": "v0.21 已完成“确认闸 + controller 内部邮箱 + worker_request_id 回信汇总”，包括 WeChat 来源结果进入 no_second_poller outbox；但 Simple 本身仍不直接启动 daemon/Codex/Claude/avatar，也不绕过既有安全纪律。",
        "test": "python3 scripts/self_check.py（覆盖本地编排、真实 mailbox dispatch fake 网络、worker_dispatch 确认闸、controller mailbox 与回复回收）。",
    },
    {
        "id": "A04",
        "module": "Agent Manager",
        "requirement": "最多 5 个 resident agents；配置名字、模型/API、能力/技能、权限；暂停/唤醒/删除；健康、context 压力、最近任务。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:130-143",
        "status": "partial",
        "evidence": "MAX_AGENTS=5，本地 agent 卡片、暂停/恢复/删除确认；真实 LingTai agents 发现、绑定、shallow spawn、退休/解绑、lull/suspend/interrupt/clear/CPR 确认闸。",
        "gap": "能力/技能/权限与模型选择还未完整绑定到真实 resident agent init/preset；删除真实 agent 仍只支持安全退休/解绑，不做销毁。",
        "test": "python3 scripts/self_check.py（覆盖 fake LingTai avatar spawn/bind/retire/lifecycle）。",
    },
    {
        "id": "A05",
        "module": "Model/API Registry",
        "requirement": "首批 GPT/OpenAI-compatible、MiMo、DeepSeek、MiniMax、GLM、自定义 base_url+api_key+model；连接测试、状态、能力标签、cost 上限/告警。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:145-167",
        "status": "partial",
        "evidence": "PROVIDER_CATALOG 已含 6 类供应商；API key 进 Keychain/env/.secrets 受限 fallback；/api/model/test 可对 OpenAI-compatible chat/completions 做真实调用，需 confirm_cost；v0.21 增加 /api/cost/status、/api/cost/policy、本地价格表、单次 provider cap、日 cap、任务 cap 与模型调用预算预检，越线先生成 budget_override approval。",
        "gap": "MiMo/MiniMax 端点需用户填写兼容 base_url；预算/成本仍是本地估算，不连接供应商真实账单/余额，默认价格表需要按实际 provider/model 校准。",
        "test": "python3 scripts/self_check.py（验证未确认费用会拒绝、预算越线生成 budget_override、key 不落盘）；真实模型测试需用户显式 confirm_cost。",
    },
    {
        "id": "A06",
        "module": "Secret Vault",
        "requirement": "Mac Keychain 优先；fallback .secrets/env slot 权限受限；启动扫描明文 key 风险；日志/报告/prompt/微信回复脱敏。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:169-182",
        "status": "partial",
        "evidence": "Keychain 通过 Security.framework/ctypes 写入，API 响应和 state 不回显 key；Keychain 不可用/被禁用时，可显式选择受限 .secrets/providers/<provider>.key fallback（目录 0700、文件 0600、拒绝 symlink/不安全权限），或使用只读 env slot；/api/health 返回 secret_vault 结构化扫描，只给位置/字段/权限/行动建议，不回显值；self_check 用假 key 验证 env/.secrets fallback、权限告警与脱敏。",
        "gap": "受限 env/.secrets fallback 已补上；已与 Model API Registry 的预算预检联动；仍未连接供应商真实账单/余额，Secret Vault 侧也不做真实扣费来源校验。",
        "test": "python3 scripts/self_check.py（Keychain disable、env slot、受限 .secrets fallback、权限告警、state/health 脱敏）；提交前高置信秘密扫描。",
    },
    {
        "id": "A07",
        "module": "Approval Queue",
        "requirement": "外发、commit/push/PR/merge、删除/公开/权限、rollback、高成本 API、Claude Code 写操作、导出日志截图报告均需确认；显示 actor/action/scope/diff/message/cost。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:184-202",
        "status": "partial",
        "evidence": "已有确认队列与 approve/deny；覆盖 rollback、delete_agent、sensitive task、Claude L3/L4/L5、LingTai lifecycle/avatar、PR/merge 等；UI 显示说明和预览文本。",
        "gap": "预算越线已有 30 分钟短时 override；但还没有通用 allow-once/allow-for-task 的细粒度授权；日志/截图/报告导出确认尚未单独实现；未越线的真实 API 调用仍采用 confirm_cost checkbox 而非队列项。",
        "test": "python3 scripts/self_check.py；destructive rollback/commit smoke 在隔离副本中验证。",
    },
    {
        "id": "A08",
        "module": "Worker / Sub-agent Pool",
        "requirement": "长期助手、临时分析、代码苦力三类工作体；界面不暴露复杂术语；Claude/Codex 权限分级。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:204-216",
        "status": "partial",
        "evidence": "UI 使用“灵/多 agent/代码苦力”等普通说法；真实 shallow avatar spawn/bind/retire；Claude Code L1-L5 已接入不同权限和确认闸；Task Router 可创建受控 worker 请求交给 controller agent。",
        "gap": "daemon/Codex/Claude/avatar 类 worker 可从 Simple Task Router 发起受控调度请求并写 controller mailbox；但 Simple 本身仍不直接启动这些 worker，长期助手技能/模型权限仍未全量写入真实 agent 配置。",
        "test": "python3 scripts/self_check.py；Claude Code 真实任务需本机 claude CLI 和显式确认。",
    },
    {
        "id": "A09",
        "module": "Memory / Skills / Knowledge / Molt",
        "requirement": "skills/knowledge/pad/molt/shougong 形成可续接记忆；长日志进文件，阶段摘要回主控；高密度协作主动生成已完成/未完成/下一步/风险/路径。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:218-232",
        "status": "done",
        "evidence": "v0.21 已实现真实 LingTai durable-store 只读索引（pad/knowledge/custom/shared skills/summaries）；/api/shougong 生成阶段成果、未竟事项、下一步、路径与风险。",
        "gap": "目前是只读索引与本地收功；写回 knowledge/skills/molt 仍交由真实 LingTai agent 流程，不由 Simple 直接修改。",
        "test": "python3 scripts/self_check.py（fake durable stores + read refusal for secrets）。",
    },
    {
        "id": "A10",
        "module": "Rollback / Time Machine",
        "requirement": "创建安全点、查看 snapshot、preview diff、二次确认后 rollback apply；醒目标注不能撤回外部副作用。",
        "source": "ARCHITECTURE_EXPERT_DISCUSSION.md:234-246",
        "status": "done",
        "evidence": "已实现 /api/rollback/snapshot、/api/rollback/preview、/api/rollback/request；批准后真实 git reset --hard，并先写 safety ref；README/UI 标明外部副作用不可回滚。",
        "gap": "仅覆盖本仓库 tracked/unignored 文件；不覆盖 VM/外部系统/已发消息。",
        "test": "python3 scripts/self_check.py；隔离 /tmp destructive rollback smoke。",
    },
    {
        "id": "A11",
        "module": "GitHub runnable packaging",
        "requirement": "任何人可从 GitHub 下载并实际运行。",
        "source": "圆酱 WeChat d53c53f8-8822-4f74-a1a9-da09c93d9cc0",
        "status": "done",
        "evidence": "已新增 run.sh、QUICKSTART.md，README 改为 clone/ZIP 运行；health 在无 .git 的 ZIP-like 目录中仍可启动并返回 ok。",
        "gap": "git Time Machine/Claude/GH/LingTai runtime 等高级能力仍需本机具备对应工具/配置；Quickstart 已说明。",
        "test": "rsync --exclude .git 到 /tmp 后 LINGTAI_SIMPLE_PORT=8899 ./run.sh，/api/health ok。",
    },
]


def architecture_acceptance_status():
    """Return the current honest implementation matrix for the architecture discussion."""
    counts = {"done": 0, "partial": 0, "missing": 0}
    for item in ARCHITECTURE_ACCEPTANCE_ITEMS:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "ok": True,
        "version": "v0.21",
        "source": "../ARCHITECTURE_EXPERT_DISCUSSION.md",
        "summary": {
            "total": len(ARCHITECTURE_ACCEPTANCE_ITEMS),
            **counts,
            "rule": "只有已真实跑通并有测试/证据的能力才标 done；未跑通一律 partial/missing。",
        },
        "items": ARCHITECTURE_ACCEPTANCE_ITEMS,
        "next_recommended_work": [
            "继续把本地预算/成本估算校准到更多 provider/model，并在可用时接供应商真实账单/余额只读查询。",
            "继续把 controller 侧 worker 执行协议标准化，让受控 worker 调度从“写信交办/回信汇总”进一步变成更稳定的可执行模板。",
            "把 Secret Vault 状态与模型调用成本/确认队列做更细粒度联动。",
        ],
    }


def health_check():
    """本地健康检查：只读，不触发外部动作。"""
    secret_scan = secret_vault_health_scan()
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
        "lingtai_network_dir": _lingtai_network_path() is not None,
        "secret_vault_scan": secret_scan.get("ok", False),
    }
    required_checks = ("localhost_only", "static_index", "static_app", "static_styles", "example_state", "state_dir", "secret_vault_scan")
    return {
        "ok": all(checks.get(k) for k in required_checks),
        "version": "v0.21",
        "host": HOST,
        "port": PORT,
        "checks": checks,
        "keychain_available": keychain_available(),
        "secret_vault": secret_scan,
        "boundaries": [
            "localhost-only",
            "real model API calls require explicit UI action (may cost money)",
            "real git Time Machine / rollback: snapshot, diff preview, confirmation-gated reset --hard",
            "real WeChat command entry via current LingTai WeChat MCP bridge; no second WeChat poller is started",
            "real unified Task Router: /api/task/route classifies one sentence into local task / multi-agent / insight / soul / shougong / LingTai mailbox / handoff",
            "real WeChat pending outbox endpoint: /api/wechat/bridge/pending for the existing MCP bridge runner",
            "real Claude Code L1 read-only analysis worker (explicit cost confirmation required)",
            "real Claude Code L2 local-edit worker: isolated worktree, validation, patch apply to this repo",
            "real Claude Code L3 commit executor: confirmation-gated local git commit only",
            "real Claude Code L4 PR executor: confirmation-gated branch push + GitHub PR creation",
            "real Claude Code L5 merge executor: confirmation-gated GitHub PR merge",
            "real local multi-agent orchestration: create/select child spirits, split objective, record task batch",
            "real local insight and soul-flow loops: deterministic state analysis, reflection records, WeChat commands",
            "real LingTai internal mailbox dispatch: Simple tasks can be queued to real agents via .lingtai/<sender>/mailbox/outbox",
            "real LingTai mailbox result collection: Simple can read matching replies from reply_inbox",
            "real LingTai lifecycle signals: confirmation-gated lull/suspend/interrupt/clear/CPR (no filesystem deletion, no nirvana)",
            "real LingTai durable-store index: read-only pad/knowledge/custom skills/shared skills/summaries view",
            "not connected yet: autonomous standalone WeChat poller",
            "Secret Vault health scan reports plaintext-key risks and unsafe fallback permissions without returning values",
            "no plaintext API key in JSON/logs/responses (Keychain-first; restricted env/.secrets fallback)",
        ],
    }


# --------------------------------------------------------------------------
# HTTP Handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LingTaiSimple/0.20"

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
                "keychain_disabled": KEYCHAIN_DISABLED,
                "secret_fallback": {
                    "policy": "Keychain-first; env slot is read-only; restricted .secrets fallback requires explicit opt-in.",
                    "env_prefix": SECRET_FALLBACK_ENV_PREFIX,
                    "secret_dir": str(SECRET_PROVIDER_DIR),
                    "file_mode": "0600",
                    "dir_mode": "0700",
                },
                "cost_policy": public_cost_policy(load_state()),
            })
        if route == "/api/cost/status":
            state = load_state()
            return self._send_json({
                "ok": True,
                "policy": public_cost_policy(state),
                "status": cost_status(state),
                "ledger": state.get("cost_ledger", [])[:100],
            })
        if route == "/api/rollback/preview":
            state = load_state()
            return self._send_json(rollback_preview(state))
        if route == "/api/health":
            return self._send_json(health_check())
        if route == "/api/secret/scan":
            return self._send_json(secret_vault_health_scan())
        if route == "/api/architecture/status":
            return self._send_json(architecture_acceptance_status())
        if route == "/api/lingtai/agents":
            return self._send_json({"agents": list_lingtai_agents(), "network_dir": LINGTAI_NETWORK_DIR})
        if route == "/api/lingtai/memory":
            return self._send_json(scan_lingtai_memory())

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
                # budget_preflight may have queued a budget_override approval/log before returning an error.
                save_state(state)
                return self._send_json({"ok": False, "error": err, "state": self._public_state(state)}, 400)
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
            result["key_source"] = spec.get("key_source")
            actual_estimate, actual_usage = estimate_model_cost_usd(state, pid, usage=result.get("usage"),
                                                                    prompt=spec.get("prompt") or "",
                                                                    max_tokens=MODEL_CALL_MAX_TOKENS)
            result["estimated_cost_usd"] = actual_estimate
            result["cost_usage_estimate"] = actual_usage
            record_cost_event(state, kind="model_call", provider_id=pid, estimated_usd=actual_estimate,
                              usage=result.get("usage") or actual_usage, source="provider_usage" if result.get("usage") else "local_estimate",
                              note=f"model={result.get('model')}; latency={result.get('latency_ms')}ms")
            log_event(state, f"真实模型调用成功：{pid} / {result.get('model')} "
                             f"（{result.get('latency_ms')}ms，估算成本≈${actual_estimate:.6f}）", kind="real_api")
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
                # budget_preflight may have queued a budget_override approval/log before returning an error.
                save_state(state)
                return self._send_json({"ok": False, "error": err, "state": self._public_state(state)}, 400)
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
            if not target.get("cost_recorded"):
                reserved = _money(_float(target.get("reserved_cost_usd"), DEFAULT_CC_RUN_CAP_USD))
                if reserved > 0:
                    record_cost_event(
                        state, kind=f"claude_code_L{level}", estimated_usd=reserved,
                        source="max_budget_reservation",
                        note=f"{label}; status={update.get('status')}; duration_ms={update.get('duration_ms')}",
                        metadata={"run_id": run.get("id"), "status": update.get("status"), "duration_ms": update.get("duration_ms")})
                target["cost_recorded"] = True
            log_event(state, f"Claude Code {label}{update['status']}：{run['id']}（{update['duration_ms']}ms）", kind="claude_code")
            save_state(state)
            ok = update["status"] in ("完成", "无改动")
            resp = {"ok": ok, "result": target, "state": self._public_state(state)}
            return self._send_json(resp, 200 if ok else 400)

    def _post_routes(self):
        return {
            "/api/agent/create": lambda s, p: create_agent(s, p),
            "/api/task/assign": lambda s, p: assign_task(s, p),
            "/api/task/route": lambda s, p: route_task(s, p),
            "/api/agent/orchestrate": lambda s, p: orchestrate_multi_agent(s, p),
            "/api/lingtai/dispatch": lambda s, p: dispatch_task_to_lingtai(s, p),
            "/api/lingtai/collect": lambda s, p: collect_lingtai_mail_results(s, p),
            "/api/lingtai/lifecycle/request": lambda s, p: request_lingtai_lifecycle(s, p),
            "/api/lingtai/avatar/request": lambda s, p: request_lingtai_avatar_spawn(s, p),
            "/api/lingtai/avatar/bind": lambda s, p: bind_lingtai_avatar(s, p),
            "/api/lingtai/avatar/retire": lambda s, p: request_lingtai_avatar_retire(s, p),
            "/api/lingtai/memory/scan": lambda s, p: record_lingtai_memory_scan(s, p),
            "/api/lingtai/memory/read": lambda s, p: read_lingtai_memory_file(s, p),
            "/api/insight/generate": lambda s, p: generate_insights(s, p),
            "/api/soul/flow": lambda s, p: generate_soul_flow(s, p),
            "/api/agent/pause": lambda s, p: set_agent_status(s, p.get("agent_id"), "pause"),
            "/api/agent/resume": lambda s, p: set_agent_status(s, p.get("agent_id"), "resume"),
            "/api/agent/delete": lambda s, p: set_agent_status(s, p.get("agent_id"), "delete"),
            "/api/approval/add": lambda s, p: add_approval(s, p),
            "/api/approval/approve": lambda s, p: resolve_approval(s, p.get("approval_id"), "approve"),
            "/api/approval/deny": lambda s, p: resolve_approval(s, p.get("approval_id"), "deny"),
            "/api/provider/save": lambda s, p: save_provider(s, p),
            "/api/provider/delete_key": lambda s, p: delete_provider_key(s, p),
            "/api/provider/check_key": lambda s, p: check_provider_key(s, p),
            "/api/cost/policy": lambda s, p: update_cost_policy(s, p),
            "/api/wechat/submit": lambda s, p: wechat_submit(s, p),
            "/api/wechat/bridge/incoming": lambda s, p: wechat_bridge_incoming(s, p),
            "/api/wechat/bridge/pending": lambda s, p: wechat_bridge_pending(s, p),
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
            "cost_policy": public_cost_policy(state),
            "cost_status": cost_status(state),
            "cost_ledger": state.get("cost_ledger", [])[:40],
            "wechat_inbox": state.get("wechat_inbox", [])[:30],
            "wechat_outbox": state.get("wechat_outbox", [])[:30],
            "wechat_bridge": state.get("wechat_bridge", {}),
            "router_runs": state.get("router_runs", [])[:30],
            "worker_requests": state.get("worker_requests", [])[:30],
            "lingtai_runtime": state.get("lingtai_runtime", {}),
            "lingtai_dispatches": state.get("lingtai_dispatches", [])[:30],
            "lingtai_mail_results": state.get("lingtai_mail_results", [])[:30],
            "lingtai_lifecycle_events": state.get("lingtai_lifecycle_events", [])[:30],
            "lingtai_avatar_events": state.get("lingtai_avatar_events", [])[:30],
            "lingtai_memory_scans": state.get("lingtai_memory_scans", [])[:20],
            "cc_runs": state.get("cc_runs", [])[:20],
            "orchestrations": state.get("orchestrations", [])[:20],
            "insights": state.get("insights", [])[:20],
            "soul_flows": state.get("soul_flows", [])[:20],
            "snapshots": state["snapshots"],
            "log": state["log"][:40],
            "stats": {
                "agent_count": len(state["agents"]),
                "max_agents": MAX_AGENTS,
                "pending_approvals": len([a for a in state["approvals"] if a["status"] == "待确认"]),
                "active_tasks": len([t for t in state["tasks"] if t["status"] in ("排队中", "执行中", "等确认")]),
                "today_estimated_cost_usd": cost_status(state).get("today_total_usd", 0.0),
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
    example["lingtai_runtime"]["status"] = "demo"
    example["lingtai_runtime"]["network_dir"] = "/path/to/.lingtai"
    example["lingtai_runtime"]["sender"] = "human"
    example["lingtai_runtime"]["reply_inbox"] = "mimo-2-5-pro"
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
        "received_at": DEMO_TIMESTAMP, "ack": "已收到 ✅（示例）",
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
    print("  圆酱专属轻量版灵台 / LingTai Simple v0.21 — 本地原型")
    print("=" * 64)
    print(f"  地址 : http://{HOST}:{PORT}/")
    print(f"  状态 : {STATE_PATH}")
    print("  边界 : localhost-only / Keychain + 模型 API + git Time Machine + 微信桥接 + Claude Code L1-L5 + LingTai 邮箱派发/回复回收/lifecycle 确认闸为真实能力")
    print("  停止 : Ctrl+C")
    print("=" * 64)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.server_close()


if __name__ == "__main__":
    main()
