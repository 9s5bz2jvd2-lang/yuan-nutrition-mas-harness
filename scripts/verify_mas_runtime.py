#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify MAS runtime provider invocation with a local OpenAI-compatible fake server.

This script intentionally uses only fake local keys and localhost HTTP. It proves
that the MAS path calls providers without requiring real OpenAI/Claude/DeepSeek/
Xiaomi credentials.
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAKE_KEY = "FAKE_MAS_RUNTIME_KEY_NOT_REAL_3333"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeProvider:
    def __init__(self):
        self.requests = []
        self.port = free_port()
        self.server = None
        self.thread = None

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}
                auth = self.headers.get("Authorization", "")
                model = payload.get("model") or "unknown-model"
                messages = payload.get("messages") or []
                user_text = ""
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        user_text = msg.get("content") or ""
                        break
                rec = {
                    "path": self.path,
                    "model": model,
                    "auth_present": bool(auth.startswith("Bearer ")),
                    "prompt_preview": user_text[:180],
                }
                outer.requests.append(rec)
                reply = f"mock-response model={model} request={len(outer.requests)} task={user_text[:80]}"
                out = {
                    "id": f"fake-{len(outer.requests)}",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                }
                data = json.dumps(out).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def req(base, path, payload=None, timeout=8):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    r = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
    return json.loads(raw.decode("utf-8"))


def wait_health(base, proc):
    deadline = time.time() + 12
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"harness server exited early: {proc.returncode}")
        try:
            h = req(base, "/api/health", None, timeout=1)
            if h.get("ok"):
                return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("harness server did not become healthy")


def main():
    fake = FakeProvider()
    fake_base = fake.start()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="yuan-mas-runtime-"))
    repo = tmp / "repo"
    def ignore(dirpath, names):
        return {n for n in names if n in {".git", "__pycache__"} or n.endswith(".pyc")}
    shutil.copytree(ROOT, repo, ignore=ignore)
    state = repo / "data" / "state.json"
    if state.exists():
        state.unlink()
    port = free_port()
    env = os.environ.copy()
    env.update({
        "LINGTAI_SIMPLE_PORT": str(port),
        "LINGTAI_SIMPLE_HOST": "127.0.0.1",
        "LINGTAI_SIMPLE_DISABLE_KEYCHAIN": "1",
        "LINGTAI_SIMPLE_KEYCHAIN_SERVICE": "lingtai-simple-mas-runtime-verify",
    })
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=str(repo), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        wait_health(base, proc)

        # Configure multiple provider IDs to the same local OpenAI-compatible fake server.
        for pid, model in [("custom", "mock-single"), ("openai", "mock-agent-a"), ("deepseek", "mock-agent-b"), ("glm", "mock-agent-c")]:
            r = req(base, "/api/provider/save", {
                "provider_id": pid,
                "base_url": fake_base,
                "model": model,
                "api_key": FAKE_KEY,
                "allow_secret_fallback": True,
            })
            assert r.get("ok"), r
            assert FAKE_KEY not in json.dumps(r, ensure_ascii=False), "fake key leaked in provider/save response"

        # Single-agent route: Task -> Route -> Agent -> Provider -> Model Call -> Response -> Result.
        a = req(base, "/api/agent/create", {"name": "Agent A", "role": "runtime verifier", "provider_id": "custom", "model": "mock-single"})
        assert a.get("ok"), a
        agent_a = a["result"]["id"]
        single = req(base, "/api/task/route", {"text": "请执行一次单 Agent provider runtime 验证", "source": "test"})
        assert single.get("ok"), single
        single_task = single["result"].get("task_id")
        single_invoke = single["result"].get("provider_invocation_id")
        assert single_task and single_invoke, single
        assert "mock-response" in single["result"].get("reply_text", ""), single["result"]

        # Multi-agent orchestration: A -> B -> C -> Coordinator final_result.
        ids = []
        for name, pid, model in [("Agent A2", "openai", "mock-agent-a"), ("Agent B", "deepseek", "mock-agent-b"), ("Agent C", "glm", "mock-agent-c")]:
            r = req(base, "/api/agent/create", {"name": name, "role": "multi verifier", "provider_id": pid, "model": model})
            assert r.get("ok"), r
            ids.append(r["result"]["id"])
        multi = req(base, "/api/agent/orchestrate", {"objective": "验证 Agent A 到 Agent B 到 Agent C 再到 Coordinator 的 provider 调用链", "agent_ids": ids, "source": "test"})
        assert multi.get("ok"), multi
        batch = multi["result"]
        assert batch.get("status") == "completed", batch
        assert len(batch.get("agent_results") or []) == 3, batch
        for row in batch["agent_results"]:
            assert row.get("provider_id") and row.get("model"), row
            assert row.get("invocation_status") == "completed", row
            assert row.get("response_status") == 200, row
            assert "mock-response" in (row.get("result") or ""), row

        state_obj = req(base, "/api/state")
        invocations = state_obj.get("provider_invocations") or []
        assert len(invocations) >= 4, invocations
        required = {"task_id", "agent_id", "provider_id", "model", "invocation_status", "response_status"}
        for inv in invocations[:4]:
            missing = [k for k in required if k not in inv]
            assert not missing, (missing, inv)
            assert inv["invocation_status"] == "completed", inv
            assert inv["response_status"] == 200, inv
        state_text = state.read_text(encoding="utf-8")
        assert FAKE_KEY not in state_text, "fake key leaked into state.json"
        assert all(x.get("auth_present") for x in fake.requests), fake.requests
        assert len(fake.requests) >= 4, fake.requests

        evidence = {
            "single_agent": {
                "task_id": single_task,
                "agent_id": agent_a,
                "provider_invocation_id": single_invoke,
                "reply_text_preview": single["result"].get("reply_text", "")[:300],
            },
            "multi_agent": {
                "orchestration_id": batch.get("id"),
                "task_ids": batch.get("task_ids"),
                "agent_results": batch.get("agent_results"),
                "final_result_preview": batch.get("final_result", "")[:500],
            },
            "provider_invocation_logs": [
                {k: inv.get(k) for k in ["task_id", "agent_id", "provider_id", "model", "invocation_status", "response_status", "status", "local_mock"]}
                for inv in invocations[:6]
            ],
            "fake_provider_requests": fake.requests,
            "secret_leak_state": "not_found",
        }
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        print("OK MAS runtime provider invocation verified with local OpenAI-compatible fake server")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
