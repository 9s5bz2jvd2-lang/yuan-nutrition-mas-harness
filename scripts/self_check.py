#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LingTai Simple v0.9 本地自检：启动临时 server，验证 GUI/API/脱敏/确认队列/Keychain。

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
    created_refs = []
    try:
        time.sleep(1.0)
        assert '圆酱' in req('/')
        health=req('/api/health'); assert health['ok'], health
        assert health['version']=='v0.9', health
        assert 'claude_code_available' in health['checks'], health
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

        # ---- 既有本地任务编排流程仍正常 ----
        a=req('/api/agent/create', {'name':'自检灵','role':'长期助手','provider_id':'openai','cc_level':'L1'})
        aid=a['result']['id']
        low=req('/api/task/assign', {'agent_id':aid,'description':'只读整理','risk':'low'}); assert low['result']['status']=='完成'
        hi=req('/api/task/assign', {'agent_id':aid,'description':'merge PR','risk':'sensitive'}); assert hi['result']['status']=='等确认'
        demo=req('/api/demo/load', {}); assert demo['ok'] and demo['result']['agents'] >= 1
        sg=req('/api/shougong', {}); assert pathlib.Path(sg['result']['path']).exists()

        # ---- Time Machine / rollback：真实创建 git snapshot，request 进入确认队列；不在原仓库执行 reset ----
        snap=req('/api/rollback/snapshot', {'label':'selfcheck-safe-point'})
        assert snap['ok'] and snap['result']['ref'].startswith('refs/lingtai-simple/snapshots/'), snap
        created_refs.append(snap['result']['ref'])
        prev=req('/api/rollback/preview')
        assert prev['git_available'] is True and any(x['id']==snap['result']['id'] for x in prev['snapshots']), prev
        rb=req('/api/rollback/request', {'snapshot_id':snap['result']['id']})
        assert rb['ok'] and rb['result']['action']=='rollback_apply' and rb['result'].get('rollback_ref'), rb

        # 再次确认：任何写盘后 state.json 仍无假 key
        # ---- WeChat bridge：真实控制端点（不启动第二个 poller），可入队、生成 outbox、状态/确认命令可用 ----
        wx=req('/api/wechat/bridge/incoming', {'text':'状态','user_id':'wx_selfcheck','message_id':'msg_selfcheck_status','sender':'圆酱'})
        assert wx['ok'] and wx['result']['should_reply'] is True, wx
        assert 'LingTai Simple v0.9' in wx['result']['reply_text'], wx
        out_id=wx['result']['outbox']['id']
        sent=req('/api/wechat/bridge/mark_sent', {'outbox_id':out_id,'sent_message_id':'sent_selfcheck_status'})
        assert sent['ok'] and sent['result']['status']=='sent', sent
        wx2=req('/api/wechat/bridge/incoming', {'text':'请帮我记录一个普通任务','user_id':'wx_selfcheck','message_id':'msg_selfcheck_task','sender':'圆酱'})
        assert wx2['ok'] and '任务队列' in wx2['result']['reply_text'], wx2
        st=req('/api/state')
        assert st['wechat_bridge']['status']=='ready' and len(st.get('wechat_outbox', []))>=2, st

        # ---- Claude Code L1：已是真实外部调用，必须显式确认费用；自检默认不烧钱，只验证未确认时拒绝、L2 未确认时拒绝；L3 本地 commit 进入真实执行确认队列；L4+ 仍只进确认队列 ----
        cc_no=req('/api/cc/request', {'level':1,'description':'只读分析 README 结构'})
        assert not cc_no['ok'] and '费用' in (cc_no.get('error') or ''), cc_no
        cc_l2_no=req('/api/cc/request', {'level':2,'description':'尝试改 README，但自检不真实执行'})
        assert not cc_l2_no['ok'] and ('费用' in (cc_l2_no.get('error') or '') or '改动确认' in (cc_l2_no.get('error') or '')), cc_l2_no
        # 为了让干净仓库也能验证 L3 入队路径，自检临时制造一个无害未跟踪文件；不批准、不 commit，finally 会删除。
        probe = ROOT/'SELF_CHECK_L3_PROBE.tmp'
        probe.write_text('LingTai Simple self-check L3 probe; not a secret.\n', encoding='utf-8')
        cc_l3=req('/api/cc/request', {'level':3,'description':'test: self-check local commit preview only'})
        assert cc_l3['ok'] and cc_l3['result'].get('queued_approval') and cc_l3['result'].get('real_executor') is True, cc_l3
        assert 'SELF_CHECK_L3_PROBE.tmp' in cc_l3['result'].get('changed_files', []), cc_l3
        st2=req('/api/state')
        assert 'cc_runs' in st2 and any(a['action']=='code_commit' for a in st2.get('approvals', [])), st2
        # L4/L5 are real executors but self-check must not push or merge. In this dirty self-check
        # context L4 should refuse before side effects; this still proves the route is guarded.
        cc_l4=req('/api/cc/request', {'level':4,'description':'test: self-check PR should not push'})
        assert not cc_l4['ok'] and ('工作区' in (cc_l4.get('error') or '') or '没有新 commit' in (cc_l4.get('error') or '') or 'GitHub' in (cc_l4.get('error') or '')), cc_l4

        assert FAKE_KEY not in state_text(state), 'FAKE KEY LEAKED after later writes!'
        print('OK LingTai Simple v0.9 self-check passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()
        if state.exists(): state.unlink()
        probe = ROOT/'SELF_CHECK_L3_PROBE.tmp'
        if probe.exists(): probe.unlink()
        for ref in created_refs:
            subprocess.run(['git','update-ref','-d',ref], cwd=ROOT, capture_output=True)
        # 清理可能残留的 Keychain 假 key（隔离 service）
        if have_security:
            subprocess.run(['security','delete-generic-password','-a','openai','-s',KC_SERVICE],
                           capture_output=True)
if __name__ == '__main__': main()
