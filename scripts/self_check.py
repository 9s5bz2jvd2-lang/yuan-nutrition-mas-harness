#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LingTai Simple v0.17 本地自检：启动临时 server，验证 GUI/API/脱敏/确认队列/Keychain。

安全约束：
- 绝不调用真实外部模型 API（不勾选 confirm_cost；只验证「未确认时被拒绝」）。
- Keychain 仅用「假 key」在隔离的 service 名下测试；测完即删。
- 无论 Keychain 写入成功还是被系统拒绝，都必须验证「假 key 没有落到 state.json」。
"""
import json, os, pathlib, shutil, subprocess, sys, time, tempfile, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('LINGTAI_SIMPLE_TEST_PORT', '8799'))
BASE = f'http://127.0.0.1:{PORT}'
# 隔离的 Keychain service，避免污染真实配置；FAKE_KEY 永不是真实凭证。
KC_SERVICE = 'lingtai-simple-selfcheck'
FAKE_KEY = 'FAKE_SELF_CHECK_KEY_NOT_REAL_0000'

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
    fake_network = pathlib.Path(tempfile.mkdtemp(prefix='lingtai-simple-selfcheck-network.'))
    (fake_network/'human'/'mailbox'/'outbox').mkdir(parents=True, exist_ok=True)
    fake_agent_dir = fake_network/'mimo-2-5-pro'
    (fake_agent_dir/'system'/'summaries').mkdir(parents=True, exist_ok=True)
    (fake_agent_dir/'knowledge'/'selfcheck').mkdir(parents=True, exist_ok=True)
    (fake_agent_dir/'.library'/'custom'/'selfcheck-skill').mkdir(parents=True, exist_ok=True)
    (fake_network/'.library_shared'/'shared-selfcheck').mkdir(parents=True, exist_ok=True)
    (fake_agent_dir/'.agent.json').write_text(json.dumps({'address':'mimo-2-5-pro','agent_name':'selfcheck-main','state':'idle'}, ensure_ascii=False), encoding='utf-8')
    (fake_agent_dir/'.status.json').write_text(json.dumps({'state':'idle'}, ensure_ascii=False), encoding='utf-8')
    (fake_agent_dir/'system'/'pad.md').write_text('# Selfcheck Pad\n\n真实记忆索引测试。\n', encoding='utf-8')
    (fake_agent_dir/'system'/'lingtai.md').write_text('# Selfcheck Character\n', encoding='utf-8')
    (fake_agent_dir/'system'/'summaries'/'molt_1.md').write_text('# Molt summary selfcheck\n', encoding='utf-8')
    (fake_agent_dir/'knowledge'/'selfcheck'/'KNOWLEDGE.md').write_text('---\nname: selfcheck-knowledge\ndescription: selfcheck durable knowledge entry\n---\n\n# Selfcheck knowledge\n', encoding='utf-8')
    (fake_agent_dir/'.library'/'custom'/'selfcheck-skill'/'SKILL.md').write_text('---\nname: selfcheck-skill\ndescription: selfcheck custom skill entry\n---\n\n# Selfcheck skill\n', encoding='utf-8')
    (fake_network/'.library_shared'/'shared-selfcheck'/'SKILL.md').write_text('---\nname: shared-selfcheck\ndescription: shared selfcheck skill entry\n---\n\n# Shared selfcheck\n', encoding='utf-8')
    (fake_agent_dir/'.secrets').mkdir(parents=True, exist_ok=True)
    (fake_agent_dir/'.secrets'/'secret.txt').write_text('SHOULD_NOT_READ', encoding='utf-8')
    (fake_network/'worker-one').mkdir(parents=True, exist_ok=True)
    (fake_network/'worker-one'/'.agent.json').write_text(json.dumps({
        'address':'worker-one', 'agent_name':'Selfcheck Worker', 'state':'idle',
        'llm': {'provider':'selfcheck', 'model':'fake'}
    }, ensure_ascii=False), encoding='utf-8')
    (fake_network/'worker-one'/'init.json').write_text(json.dumps({
        'manifest': {'agent_name':'worker-one', 'admin': {}, 'preset': {'allowed': [], 'default': ''}},
        'prompt':'', 'comment':'selfcheck template'
    }, ensure_ascii=False), encoding='utf-8')
    fake_agent_cmd = fake_network/'fake-lingtai-agent.py'
    fake_agent_cmd.write_text('''#!/usr/bin/env python3
import json, pathlib, sys, time
agent_dir = pathlib.Path(sys.argv[-1])
name = agent_dir.name
(agent_dir/".agent.json").write_text(json.dumps({"address":name,"agent_name":name,"state":"idle","llm":{"provider":"fake","model":"fake"}}, ensure_ascii=False), encoding="utf-8")
(agent_dir/".agent.heartbeat").write_text(str(time.time()), encoding="utf-8")
time.sleep(30)
''', encoding='utf-8')
    fake_agent_cmd.chmod(0o700)
    env = {**os.environ, 'LINGTAI_SIMPLE_PORT': str(PORT),
           'LINGTAI_SIMPLE_KEYCHAIN_SERVICE': KC_SERVICE,
           'LINGTAI_SIMPLE_NETWORK_DIR': str(fake_network),
           'LINGTAI_SIMPLE_AGENT_DIR': str(fake_agent_dir),
           'LINGTAI_SIMPLE_MAIL_SENDER': 'human',
           'LINGTAI_SIMPLE_REPLY_INBOX': 'mimo-2-5-pro',
           'LINGTAI_SIMPLE_AGENT_CMD': str(fake_agent_cmd)}
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    created_refs = []
    try:
        time.sleep(1.0)
        assert '圆酱' in req('/')
        health=req('/api/health'); assert health['ok'], health
        assert health['version']=='v0.17', health
        assert 'claude_code_available' in health['checks'], health
        assert health['keychain_available'] == have_security, health
        assert health['checks'].get('secret_vault_scan') is True, health
        assert health['secret_vault']['summary']['high'] == 0, health
        boundaries=' '.join(health['boundaries'])
        assert 'real WeChat command entry' in boundaries
        assert 'durable-store index' in boundaries, health
        arch=req('/api/architecture/status')
        assert arch['ok'] and arch['version']=='v0.17' and arch['summary']['total'] >= 10, arch
        assert arch['summary']['done'] >= 4 and arch['summary']['partial'] >= 1, arch
        assert any(i['id']=='A01' and i['status']=='partial' for i in arch['items']), arch
        assert any(i['id']=='A11' and i['status']=='done' for i in arch['items']), arch
        assert any(i['id']=='A06' and 'health scan' in i['test'] for i in arch['items']), arch
        mem=req('/api/lingtai/memory')
        assert mem['ok'] and mem['counts']['pad'] >= 2 and mem['counts']['knowledge'] >= 1 and mem['counts']['skills'] >= 2, mem
        scan=req('/api/lingtai/memory/scan', {})
        assert scan['ok'] and scan['result']['counts']['knowledge'] >= 1, scan
        pad_read=req('/api/lingtai/memory/read', {'path': str(fake_agent_dir/'system'/'pad.md'), 'max_chars': 2000})
        assert pad_read['ok'] and '真实记忆索引测试' in pad_read['result']['content'], pad_read
        forbidden=req('/api/lingtai/memory/read', {'path': str(fake_agent_dir/'.secrets'/'secret.txt')})
        assert not forbidden['ok'] and ('允许' in (forbidden.get('error') or '') or '拒绝' in (forbidden.get('error') or '')), forbidden
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

        # ---- Secret Vault health scan：只返回位置/字段，不回显值；能发现临时明文风险 ----
        risk_file = ROOT/'data'/'secret_health_selfcheck.json'
        risk_value = 'selfcheck-risk-value'
        risk_file.write_text(json.dumps({'api_key': risk_value}, ensure_ascii=False), encoding='utf-8')
        secscan=req('/api/secret/scan')
        assert secscan['summary']['high'] >= 1, secscan
        assert risk_value not in json.dumps(secscan, ensure_ascii=False), secscan
        assert any(r.get('field_path') == 'api_key' for r in secscan.get('risks', [])), secscan
        risk_file.unlink()
        health2=req('/api/health')
        assert health2['checks'].get('secret_vault_scan') is True, health2

        # ---- 真实模型调用必须显式确认；未确认时拒绝、且不发起网络 ----
        mt=req('/api/model/test', {'provider_id':'openai'})
        assert not mt['ok'] and '费用' in (mt.get('error') or ''), mt

        # ---- 既有本地任务编排流程仍正常 ----
        a=req('/api/agent/create', {'name':'自检灵','role':'长期助手','provider_id':'openai','cc_level':'L1'})
        aid=a['result']['id']
        low=req('/api/task/assign', {'agent_id':aid,'description':'只读整理','risk':'low'}); assert low['result']['status']=='完成'
        hi=req('/api/task/assign', {'agent_id':aid,'description':'merge PR','risk':'sensitive'}); assert hi['result']['status']=='等确认'

        # ---- v0.14 真实 LingTai 内部邮箱派发：在隔离 fake .lingtai 网络中写 outbox，不碰真实邮箱 ----
        discovered=req('/api/lingtai/agents')
        assert any(a.get('address')=='worker-one' for a in discovered['agents']), discovered
        no_confirm=req('/api/lingtai/dispatch', {'task_id':low['result']['id'], 'address':'worker-one'})
        assert not no_confirm['ok'] and 'confirm_dispatch' in (no_confirm.get('error') or ''), no_confirm
        disp=req('/api/lingtai/dispatch', {'task_id':low['result']['id'], 'address':'worker-one', 'confirm_dispatch': True})
        assert disp['ok'] and disp['result']['to']=='worker-one' and disp['result']['from']=='human', disp
        outbox_path=pathlib.Path(disp['result']['outbox_path'])/'message.json'
        assert outbox_path.exists(), disp
        msg=json.loads(outbox_path.read_text(encoding='utf-8'))
        assert msg['to']==['worker-one'] and msg['from']=='human' and '只读整理' in msg['message'], msg
        st_mail=req('/api/state')
        assert st_mail.get('lingtai_dispatches') and st_mail['tasks'][0]['status'] in ('已派发','等确认','完成'), st_mail

        # ---- v0.14 真实 LingTai 回复回收：在隔离 fake reply_inbox 中放入匹配回信，再只读回收到 Simple 状态 ----
        inbox_dir=fake_network/'mimo-2-5-pro'/'mailbox'/'inbox'/'reply-selfcheck-0001'
        inbox_dir.mkdir(parents=True, exist_ok=True)
        reply_msg={
            '_mailbox_id':'reply-selfcheck-0001',
            'from':'worker-one',
            'to':['mimo-2-5-pro'],
            'subject':'Re: '+disp['result']['subject'],
            'message':'Selfcheck worker reply for dispatch '+disp['result']['mailbox_id']+'：真实回收链路 OK',
            'received_at':'2026-06-05T00:00:00Z',
        }
        (inbox_dir/'message.json').write_text(json.dumps(reply_msg, ensure_ascii=False), encoding='utf-8')
        coll=req('/api/lingtai/collect', {})
        assert coll['ok'] and coll['result']['collected']==1, coll
        st_reply=req('/api/state')
        assert st_reply.get('lingtai_mail_results') and st_reply['lingtai_dispatches'][0]['status']=='reply_received', st_reply

        # ---- v0.14 真实 LingTai 生命周期确认闸：只加入确认队列，不在 self-check 中执行真实 signal/CPR ----
        life=req('/api/lingtai/lifecycle/request', {'address':'worker-one','action':'lull'})
        assert life['ok'] and life['result']['action']=='lingtai_lifecycle' and life['result']['lingtai_address']=='worker-one', life

        # ---- v0.14 真实 avatar 绑定/退休安全语义：绑定既有真实 agent；删除入口只变成退休/解绑，不删除目录 ----
        bind=req('/api/lingtai/avatar/bind', {'address':'worker-one','name':'Worker One Bound','role':'self-check bound real agent'})
        assert bind['ok'] and bind['result']['agent']['lingtai_address']=='worker-one', bind
        bound_id=bind['result']['agent']['id']
        retire_from_delete=req('/api/agent/delete', {'agent_id': bound_id})
        assert retire_from_delete['ok'] and retire_from_delete['result']['mode']=='retire_not_delete', retire_from_delete
        st_retq=req('/api/state')
        assert st_retq['approvals'][0]['action']=='lingtai_avatar_retire' and st_retq['approvals'][0]['lingtai_address']=='worker-one', st_retq['approvals'][0]
        ret_ok=req('/api/approval/approve', {'approval_id': st_retq['approvals'][0]['id']})
        assert ret_ok['ok'] and (fake_network/'worker-one').exists(), ret_ok
        st_retdone=req('/api/state')
        assert any(a.get('lingtai_address')=='worker-one' and a.get('lingtai_retired') for a in st_retdone['agents']), st_retdone['agents']

        # ---- v0.14 真实 avatar spawn 确认闸：只入队，不在 self-check 中启动真实长期 agent ----
        av_short=req('/api/lingtai/avatar/request', {'name':'selfcheck-avatar','template_address':'worker-one','mission':'test'})
        assert not av_short['ok'] and 'mission' in (av_short.get('error') or ''), av_short
        av=req('/api/lingtai/avatar/request', {
            'name':'selfcheck-avatar', 'template_address':'worker-one',
            'mission':'Self-check avatar mission: verify the real spawn approval gate without executing the spawn.',
            'confirm_mission': True,
        })
        assert av['ok'] and av['result']['action']=='lingtai_avatar_spawn' and av['result']['avatar_name']=='selfcheck-avatar', av
        assert not (fake_network/'selfcheck-avatar').exists(), 'avatar directory should not be created before approval'
        av_ok=req('/api/approval/approve', {'approval_id': av['result']['id']})
        assert av_ok['ok'] and (fake_network/'selfcheck-avatar'/'init.json').exists(), av_ok
        assert (fake_network/'selfcheck-avatar'/'.prompt').exists(), 'spawn should write .prompt'
        st_av=req('/api/state')
        assert st_av.get('lingtai_avatar_events') and st_av['lingtai_avatar_events'][0]['address']=='selfcheck-avatar', st_av

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
        assert 'LingTai Simple v0.17' in wx['result']['reply_text'], wx
        out_id=wx['result']['outbox']['id']
        sent=req('/api/wechat/bridge/mark_sent', {'outbox_id':out_id,'sent_message_id':'sent_selfcheck_status'})
        assert sent['ok'] and sent['result']['status']=='sent', sent
        wx2=req('/api/wechat/bridge/incoming', {'text':'请帮我记录一个普通任务','user_id':'wx_selfcheck','message_id':'msg_selfcheck_task','sender':'圆酱'})
        assert wx2['ok'] and '任务队列' in wx2['result']['reply_text'], wx2
        st=req('/api/state')
        assert st['wechat_bridge']['status']=='ready' and len(st.get('wechat_outbox', []))>=2, st

        # ---- v0.14 多 agent / 洞察 / 心流：真实本地状态能力，微信桥接也能触发 ----
        orch=req('/api/agent/orchestrate', {'objective':'自检：把专属轻量版灵台拆给多个子灵', 'source':'self_check'})
        assert orch['ok'] and orch['result']['task_ids'] and orch['result']['insight_id'], orch
        st_orch=req('/api/state')
        assert st_orch.get('orchestrations') and st_orch.get('insights'), st_orch
        ins=req('/api/insight/generate', {'focus':'自检：检查风险和下一步'})
        assert ins['ok'] and ins['result']['findings'], ins
        soul=req('/api/soul/flow', {'trigger':'self_check'})
        assert soul['ok'] and '心流回环' in soul['result']['text'], soul
        wx_ins=req('/api/wechat/bridge/incoming', {'text':'洞察 多agent和心流是否可用','user_id':'wx_selfcheck','message_id':'msg_selfcheck_insight','sender':'圆酱'})
        assert wx_ins['ok'] and '洞察' in wx_ins['result']['reply_text'], wx_ins
        wx_soul=req('/api/wechat/bridge/incoming', {'text':'心流 自检','user_id':'wx_selfcheck','message_id':'msg_selfcheck_soul','sender':'圆酱'})
        assert wx_soul['ok'] and '心流回环' in wx_soul['result']['reply_text'], wx_soul
        wx_orch=req('/api/wechat/bridge/incoming', {'text':'多agent 做一个认真版本','user_id':'wx_selfcheck','message_id':'msg_selfcheck_orch','sender':'圆酱'})
        assert wx_orch['ok'] and '批次' in wx_orch['result']['reply_text'], wx_orch

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
        print('OK LingTai Simple v0.17 self-check passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()
        if state.exists(): state.unlink()
        shutil.rmtree(fake_network, ignore_errors=True)
        probe = ROOT/'SELF_CHECK_L3_PROBE.tmp'
        if probe.exists(): probe.unlink()
        for ref in created_refs:
            subprocess.run(['git','update-ref','-d',ref], cwd=ROOT, capture_output=True)
        # 清理可能残留的 Keychain 假 key（隔离 service）
        if have_security:
            subprocess.run(['security','delete-generic-password','-a','openai','-s',KC_SERVICE],
                           capture_output=True)
if __name__ == '__main__': main()
