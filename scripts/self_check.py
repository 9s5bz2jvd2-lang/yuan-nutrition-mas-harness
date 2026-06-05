#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LingTai Simple v0.3 本地自检：启动临时 server，验证 GUI/API/脱敏/确认队列/Keychain。

安全约束：
- 绝不调用真实外部模型 API（不勾选 confirm_cost；只验证「未确认时被拒绝」）。
- Keychain 仅用「假 key」在隔离的 service 名下测试；测完即删。
- 无论 Keychain 写入成功还是被系统拒绝，都必须验证「假 key 没有落到 state.json」。
"""
import json, os, pathlib, shutil, subprocess, sys, time, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('LINGTAI_SIMPLE_TEST_PORT', '8799'))
BASE = f'http://127.0.0.1:{PORT}'
# 隔离的 Keychain service，避免污染真实配置；FAKE_KEY 永不是真实凭证。
KC_SERVICE = 'lingtai-simple-selfcheck'
FAKE_KEY = 'sk-FAKE-selfcheck-NOT-A-REAL-KEY-0000'

def req(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    r = urllib.request.Request(BASE + path, data=data, headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        # 4xx/5xx 也带 JSON 体（如 {"ok": false, "error": ...}）；读出来返回。
        body = e.read()
    try: return json.loads(body.decode('utf-8'))
    except Exception: return body.decode('utf-8', errors='replace')

def state_text(state):
    return state.read_text(encoding='utf-8') if state.exists() else ''


def main():
    state = ROOT/'data'/'state.json'
    if state.exists(): state.unlink()
    have_security = shutil.which('security') is not None
    env = {**os.environ, 'LINGTAI_SIMPLE_PORT': str(PORT),
           'LINGTAI_SIMPLE_KEYCHAIN_SERVICE': KC_SERVICE}
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        time.sleep(1.0)
        assert '圆酱' in req('/')
        health=req('/api/health'); assert health['ok'], health
        assert health['version']=='v0.3', health
        assert health['keychain_available'] == have_security, health
        catalog=req('/api/catalog')
        assert len(catalog['providers'])>=6 and catalog['max_agents']==5
        assert 'keychain_available' in catalog
        # 每个供应商应有 default_model 字段（UI 默认填充）
        assert all('default_model' in p for p in catalog['providers']), catalog['providers']

        # ---- 供应商保存：保存 base_url/model（不带 key），不应有明文 ----
        r=req('/api/provider/save', {'provider_id':'openai','base_url':'https://api.example.invalid/v1','model':'gpt-test'})
        assert r['ok'] and 'api_key' not in r['result'], r
        assert r['result']['base_url']=='https://api.example.invalid/v1'

        # ---- Keychain：用假 key 走真实 security CLI（若可用）----
        kc_save = req('/api/provider/save', {'provider_id':'openai','base_url':'https://api.example.invalid/v1','model':'gpt-test','api_key':FAKE_KEY,'key_label':'selfcheck'})
        if have_security:
            # 写入可能成功，也可能被系统拒绝（无交互 session / 锁定 keychain）。
            # 两种情况都可接受，但都必须保证：假 key 没有落到 state.json。
            if kc_save['ok']:
                assert kc_save['result']['in_keychain'] is True, kc_save
                assert kc_save['result']['key_last4']=='0000' and 'api_key' not in kc_save['result'], kc_save
                # check_key 应报告 in_keychain=True
                chk=req('/api/provider/check_key', {'provider_id':'openai'})
                assert chk['ok'] and chk['result']['in_keychain'] is True, chk
                # delete_key 应移除
                dele=req('/api/provider/delete_key', {'provider_id':'openai'})
                assert dele['ok'] and dele['result']['in_keychain'] is False, dele
                chk2=req('/api/provider/check_key', {'provider_id':'openai'})
                assert chk2['result']['in_keychain'] is False, chk2
                print('  · Keychain 读写删 OK（security CLI 可写入）')
            else:
                # 被系统拒绝 → 必须是失败而非退化为明文存储
                print('  · Keychain 写入被系统拒绝（无交互 session）；已确认未退化为明文存储')
        else:
            # 非 macOS：保存 key 必须被拒绝（不退化为明文）
            assert not kc_save['ok'], kc_save
            print('  · 无 security CLI：保存 key 被正确拒绝（不落明文）')

        # ---- 关键安全断言：假 key 绝不出现在 state.json ----
        assert FAKE_KEY not in state_text(state), 'FAKE KEY LEAKED INTO state.json!'

        # ---- 真实模型调用必须显式确认；未确认时拒绝、且不发起网络 ----
        mt=req('/api/model/test', {'provider_id':'openai'})
        assert not mt['ok'] and '费用' in (mt.get('error') or ''), mt

        # ---- 既有 mock 流程仍正常 ----
        a=req('/api/agent/create', {'name':'自检灵','role':'长期助手','provider_id':'openai','cc_level':'L1'})
        aid=a['result']['id']
        low=req('/api/task/assign', {'agent_id':aid,'description':'只读整理','risk':'low'}); assert low['result']['status']=='完成'
        hi=req('/api/task/assign', {'agent_id':aid,'description':'merge PR','risk':'sensitive'}); assert hi['result']['status']=='等确认'
        demo=req('/api/demo/load', {}); assert demo['ok'] and demo['result']['agents'] >= 1
        sg=req('/api/shougong', {}); assert pathlib.Path(sg['result']['path']).exists()

        # 再次确认：任何写盘后 state.json 仍无假 key
        assert FAKE_KEY not in state_text(state), 'FAKE KEY LEAKED after later writes!'
        print('OK LingTai Simple v0.3 self-check passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()
        if state.exists(): state.unlink()
        # 清理可能残留的 Keychain 假 key（隔离 service）
        if have_security:
            subprocess.run(['security','delete-generic-password','-a','openai','-s',KC_SERVICE],
                           capture_output=True)
if __name__ == '__main__': main()
