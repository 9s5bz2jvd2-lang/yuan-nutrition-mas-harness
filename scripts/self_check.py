#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yuan Nutrition MAS Harness v0.24 本地自检：启动临时 server，验证 GUI/API/脱敏/确认队列/Keychain。

安全约束：
- 绝不调用真实外部模型 API（不勾选 confirm_cost；只验证「未确认时被拒绝」）。
- 默认用 LINGTAI_SIMPLE_DISABLE_KEYCHAIN=1 强制走 env/.secrets fallback，避免污染真实 Keychain。
- 所有假 key 都必须验证不落到 state.json / health / scan 响应。
"""
import json, os, pathlib, re, shutil, subprocess, sys, time, tempfile, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('LINGTAI_SIMPLE_TEST_PORT', '8799'))
BASE = f'http://127.0.0.1:{PORT}'
# 隔离的 Keychain service，避免污染真实配置；FAKE_KEY 永不是真实凭证。
KC_SERVICE = 'lingtai-simple-selfcheck'
FAKE_KEY = 'FAKE_SELF_CHECK_KEY_NOT_REAL_0000'
FAKE_ENV_KEY = 'FAKE_ENV_SELF_CHECK_KEY_NOT_REAL_1111'
FAKE_FALLBACK_KEY = 'FAKE_FALLBACK_SELF_CHECK_KEY_NOT_REAL_2222'
SECRET_VALUE_RE = re.compile(r'(sk-[A-Za-z0-9_\-]{12,}|Bearer\s+[A-Za-z0-9_\-\.]{12,}|ghp_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]+)')

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
           'LINGTAI_SIMPLE_AGENT_CMD': str(fake_agent_cmd),
           'LINGTAI_SIMPLE_DISABLE_KEYCHAIN': '1',
           'LINGTAI_SIMPLE_API_KEY_DEEPSEEK': FAKE_ENV_KEY}
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    created_refs = []
    try:
        time.sleep(1.0)
        assert '圆酱' in req('/')
        health=req('/api/health'); assert health['ok'], health
        assert health['version']=='v0.24', health
        assert 'claude_code_available' in health['checks'], health
        assert health['keychain_available'] is False, health
        assert health['checks'].get('secret_vault_scan') is True, health
        assert health['secret_vault']['summary']['high'] == 0, health
        boundaries=' '.join(health['boundaries'])
        assert 'real WeChat command entry' in boundaries
        assert 'durable-store index' in boundaries, health
        standalone=req('/api/standalone/status')
        assert standalone['ok'] and standalone['core_runtime']['ok'] is True, standalone
        assert standalone['core_startup']['ok'] is True and standalone['core_startup']['server']=='running', standalone
        assert standalone['core_startup']['requires_full_lingtai'] is False, standalone
        assert standalone.get('missing_core') == [], standalone
        assert standalone['optional_bridge']['requires_full_lingtai'] is False, standalone
        assert standalone['optional_bridge']['required_for_core_startup'] is False, standalone
        assert standalone['standalone_capabilities']['local_gui_task_queue']['available'] is True, standalone
        assert standalone['standalone_capabilities']['approvals']['available'] is True, standalone
        assert standalone['standalone_capabilities']['harness_run_state']['available'] is True, standalone
        assert standalone['standalone_capabilities']['cost_guardrails']['available'] is True, standalone
        standalone_text=json.dumps(standalone, ensure_ascii=False)
        assert FAKE_KEY not in standalone_text and FAKE_ENV_KEY not in standalone_text and FAKE_FALLBACK_KEY not in standalone_text, standalone
        assert not SECRET_VALUE_RE.search(standalone_text), standalone
        arch=req('/api/architecture/status')
        assert arch['ok'] and arch['version']=='v0.24' and arch['summary']['total'] >= 10, arch
        assert arch['summary']['done'] >= 4 and arch['summary']['partial'] >= 1, arch
        assert any(i['id']=='A01' and i['status']=='partial' for i in arch['items']), arch
        assert any(i['id']=='A11' and i['status']=='done' for i in arch['items']), arch
        assert any(i['id']=='A06' and '.secrets fallback' in i['evidence'] for i in arch['items']), arch
        assert any(i['id']=='A08' and 'Worker 启动器' in i['evidence'] for i in arch['items']), arch
        catalog=req('/api/catalog')
        assert catalog.get('worker_launchers') and all(k in catalog['worker_launchers'] for k in ('daemon','codex','claude','avatar')), catalog
        wl_status=req('/api/worker/launcher/status')
        assert wl_status['ok'] and wl_status['version']=='v0.24-worker-launcher' and wl_status['launchers']['daemon']['available'] is True, wl_status
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
        assert 'keychain_available' in catalog and catalog['keychain_available'] is False
        assert catalog.get('keychain_disabled') is True, catalog
        assert catalog.get('secret_fallback', {}).get('env_prefix') == 'LINGTAI_SIMPLE_API_KEY_', catalog
        assert catalog.get('cost_policy', {}).get('currency') == 'USD', catalog
        assert catalog['cost_policy']['daily_cap_usd'] > 0 and catalog['cost_policy']['provider_call_cap_usd'] > 0, catalog
        # 每个供应商应有 default_model 字段（UI 默认填充）
        assert all('default_model' in p for p in catalog['providers']), catalog['providers']

        # ---- v0.20 预算/成本面板：本地估算策略可读可改，越线会进确认队列而不会发起真实网络调用 ----
        cost0=req('/api/cost/status')
        assert cost0['ok'] and cost0['policy']['currency']=='USD' and cost0['status']['today_total_usd'] == 0, cost0
        pol=req('/api/cost/policy', {'provider_call_cap_usd': 0.000001, 'daily_cap_usd': 5.0, 'reset_ledger': True})
        assert pol['ok'] and pol['result']['policy']['provider_call_cap_usd'] == 0.000001, pol

        # ---- 供应商保存：保存 base_url/model（不带 key），不应有明文 ----
        r=req('/api/provider/save', {'provider_id':'openai','base_url':'https://api.example.invalid/v1','model':'gpt-test'})
        assert r['ok'] and 'api_key' not in r['result'], r
        assert r['result']['base_url']=='https://api.example.invalid/v1'

        # ---- Secret Vault fallback：Keychain 被禁用时，默认拒绝明文/非授权落盘 ----
        kc_save = req('/api/provider/save', {'provider_id':'openai','base_url':'https://api.example.invalid/v1','model':'gpt-test','api_key':FAKE_KEY,'key_label':'selfcheck'})
        assert not kc_save['ok'] and 'allow_secret_fallback' in (kc_save.get('error') or ''), kc_save

        # env slot 是只读 fallback：能被检测/用于状态，但绝不回显值。
        env_chk=req('/api/provider/check_key', {'provider_id':'deepseek'})
        assert env_chk['ok'] and env_chk['result']['key_source']=='env' and env_chk['result']['env_slot_present'] is True, env_chk
        assert FAKE_ENV_KEY not in json.dumps(env_chk, ensure_ascii=False), env_chk

        # 显式允许后，写入受限 .secrets/providers/<provider>.key（0600 under 0700 dirs）。
        fb_save=req('/api/provider/save', {
            'provider_id':'glm','base_url':'https://open.bigmodel.cn/api/paas/v4','model':'glm-4-flash',
            'api_key':FAKE_FALLBACK_KEY,'key_label':'fallback-selfcheck','allow_secret_fallback': True})
        assert fb_save['ok'] and fb_save['result']['key_source']=='secret_file' and fb_save['result']['secret_file_present'] is True, fb_save
        assert fb_save['result']['key_last4']=='2222' and 'api_key' not in fb_save['result'], fb_save
        secret_path = ROOT/'.secrets'/'providers'/'glm.key'
        assert secret_path.exists(), secret_path
        assert (secret_path.stat().st_mode & 0o777) == 0o600, oct(secret_path.stat().st_mode & 0o777)
        assert ((ROOT/'.secrets').stat().st_mode & 0o077) == 0, oct((ROOT/'.secrets').stat().st_mode & 0o777)
        assert ((ROOT/'.secrets'/'providers').stat().st_mode & 0o077) == 0, oct((ROOT/'.secrets'/'providers').stat().st_mode & 0o777)
        fb_chk=req('/api/provider/check_key', {'provider_id':'glm'})
        assert fb_chk['ok'] and fb_chk['result']['key_source']=='secret_file', fb_chk
        assert FAKE_FALLBACK_KEY not in json.dumps(fb_chk, ensure_ascii=False), fb_chk

        # ---- 关键安全断言：假 key 绝不出现在 state.json/API 响应 ----
        assert FAKE_KEY not in state_text(state), 'FAKE KEY LEAKED INTO state.json!'
        assert FAKE_ENV_KEY not in state_text(state), 'ENV FAKE KEY LEAKED INTO state.json!'
        assert FAKE_FALLBACK_KEY not in state_text(state), 'FALLBACK FAKE KEY LEAKED INTO state.json!'

        # ---- Secret Vault health scan：只返回位置/字段/权限，不回显值；能发现临时明文风险与不安全 fallback 权限 ----
        secscan_clean=req('/api/secret/scan')
        assert secscan_clean['fallback']['secret_files'] and secscan_clean['summary']['high'] == 0, secscan_clean
        assert FAKE_FALLBACK_KEY not in json.dumps(secscan_clean, ensure_ascii=False), secscan_clean
        risk_file = ROOT/'data'/'secret_health_selfcheck.json'
        risk_value = 'selfcheck-risk-value'
        risk_file.write_text(json.dumps({'api_key': risk_value}, ensure_ascii=False), encoding='utf-8')
        secscan=req('/api/secret/scan')
        assert secscan['summary']['high'] >= 1, secscan
        assert risk_value not in json.dumps(secscan, ensure_ascii=False), secscan
        assert any(r.get('field_path') == 'api_key' for r in secscan.get('risks', [])), secscan
        risk_file.unlink()
        os.chmod(secret_path, 0o644)
        secscan_unsafe=req('/api/secret/scan')
        assert secscan_unsafe['summary']['high'] >= 1 and any(w.get('kind')=='secret_file_permission_unsafe' for w in secscan_unsafe.get('warnings', [])), secscan_unsafe
        assert FAKE_FALLBACK_KEY not in json.dumps(secscan_unsafe, ensure_ascii=False), secscan_unsafe
        os.chmod(secret_path, 0o600)
        health2=req('/api/health')
        assert health2['checks'].get('secret_vault_scan') is True, health2

        # ---- 真实模型调用必须显式确认；未确认时拒绝、且不发起网络 ----
        mt=req('/api/model/test', {'provider_id':'openai'})
        assert not mt['ok'] and '费用' in (mt.get('error') or ''), mt
        # confirm_cost=true 但预算单次上限被调低时，应先被预算闸拦截并生成 budget_override；
        # 因为在 prepare 阶段已拦截，这一步不会发起真实 HTTP 模型请求。
        mt_budget=req('/api/model/test', {'provider_id':'deepseek','confirm_cost':True,'prompt':'self-check budget gate'})
        assert not mt_budget['ok'] and '预算/成本策略已拦截' in (mt_budget.get('error') or ''), mt_budget
        st_budget=req('/api/state')
        budget_ap=next((a for a in st_budget.get('approvals', []) if a.get('action')=='budget_override' and a.get('status')=='待确认'), None)
        assert budget_ap and budget_ap.get('cost_kind')=='model_call' and budget_ap.get('cost_provider_id')=='deepseek', st_budget.get('approvals')
        budget_ok=req('/api/approval/approve', {'approval_id': budget_ap['id']})
        assert budget_ok['ok'] and budget_ok['result']['status']=='已确认', budget_ok
        cost1=req('/api/cost/status')
        assert cost1['ok'] and any(o.get('kind')=='model_call' and o.get('provider_id')=='deepseek' for o in cost1['policy'].get('active_overrides', [])), cost1

        # ---- v0.23 scoped approval grants: allow-once creates a bounded grant; the next same action is auto-confirmed ----
        manual_ap=req('/api/approval/add', {
            'action':'sensitive_task', 'title':'self-check scoped grant seed',
            'detail':'local-only self-check action, no external side effect',
            'task_id':'task_selfcheck_grant', 'agent_id':'agent_selfcheck_grant'
        })
        assert manual_ap['ok'] and manual_ap['result']['status']=='待确认', manual_ap
        grant_seed_id=manual_ap['result']['id']
        grant_ok=req('/api/approval/approve', {'approval_id': grant_seed_id, 'grant_scope':'once'})
        assert grant_ok['ok'], grant_ok
        grants=grant_ok['state'].get('approval_grants', {})
        assert grants.get('active_count') == 1 and grants['active'][0]['action']=='sensitive_task' and grants['active'][0]['scope']=='once', grants
        auto_ap=req('/api/approval/add', {
            'action':'sensitive_task', 'title':'self-check scoped grant auto',
            'detail':'should be auto-confirmed by allow-once grant',
            'task_id':'task_selfcheck_grant_auto', 'agent_id':'agent_selfcheck_grant'
        })
        assert auto_ap['ok'], auto_ap
        auto_res=auto_ap['result']
        assert auto_res['status']=='grant自动确认' and auto_res.get('grant_id'), auto_res
        st_grant=auto_ap['state']
        assert st_grant.get('approval_grants', {}).get('active_count') == 0, st_grant.get('approval_grants')
        used_grant=next((g for g in st_grant.get('approval_grants', {}).get('recent', []) if g.get('id')==auto_res.get('grant_id')), None)
        assert used_grant and used_grant.get('status')=='used' and auto_res['id'] in used_grant.get('used_by', []), used_grant
        # Destructive actions remain per-item only and cannot be turned into a scoped grant.
        destructive=req('/api/approval/add', {'action':'code_merge', 'title':'self-check no scoped grant for merge', 'detail':'do not execute'})
        assert destructive['ok'] and destructive['result']['status']=='待确认', destructive
        bad_grant=req('/api/approval/approve', {'approval_id': destructive['result']['id'], 'grant_scope':'once'})
        assert not bad_grant['ok'] and '逐项确认' in bad_grant.get('error',''), bad_grant
        deny_destructive=req('/api/approval/deny', {'approval_id': destructive['result']['id']})
        assert deny_destructive['ok'], deny_destructive

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

        # ---- v0.18 统一 Task Router：普通任务、本地路由记录、真实 mailbox dispatch 在 fake 网络中走通 ----
        route_local=req('/api/task/route', {'text':'自检：通过统一路由记录一个普通任务', 'source':'self_check'})
        assert route_local['ok'] and route_local['result']['route_type']=='local_task' and route_local['result'].get('task_id'), route_local
        st_route=req('/api/state')
        assert st_route.get('router_runs') and st_route['router_runs'][0]['id']==route_local['result']['id'], st_route.get('router_runs')
        hs0=req('/api/harness/status')
        assert hs0['ok'] and hs0['version']=='v0.24' and hs0['counts']['total_runs'] >= 1, hs0
        assert 'watchdog' in hs0 and 'needs_attention' in hs0 and 'last_activity_age_seconds' in hs0, hs0
        assert st_route.get('harness_runs') and st_route['harness_runs'][0].get('protocol') and st_route['harness_runs'][0].get('route_id')==route_local['result']['id'], st_route.get('harness_runs')

        # ---- v0.24 follow-up read-only Harness Watchdog：标出久未回收/需人工介入的 run，不产生外部副作用 ----
        st_for_watch=json.loads(state.read_text(encoding='utf-8'))
        stale_run={
            'id':'harness_selfcheck_stale',
            'created_at':'2000-01-01T00:00:00+00:00',
            'updated_at':'2000-01-01T00:00:00+00:00',
            'source':'self_check',
            'return_channel':'ui',
            'input':'self-check stale dispatched harness run',
            'route_type':'lingtai_mailbox',
            'status':'dispatched',
            'protocol':'intake -> route -> approval -> dispatch -> collect -> return',
            'stages':[{'name':'dispatch','status':'done','at':'2000-01-01T00:00:00+00:00'}],
            'artifacts':[],
            'risk_gates':[],
        }
        st_for_watch.setdefault('harness_runs', []).insert(0, stale_run)
        state.write_text(json.dumps(st_for_watch, ensure_ascii=False, indent=2), encoding='utf-8')
        hs_watch=req('/api/harness/status')
        assert hs_watch['ok'] and hs_watch['needs_attention'] is True and hs_watch['stale_dispatched'] >= 1, hs_watch
        watched=next((r for r in hs_watch['recent_runs'] if r.get('id')=='harness_selfcheck_stale'), None)
        assert watched and watched['stale_dispatched'] is True and watched['needs_attention'] is True, hs_watch.get('recent_runs')
        assert watched['recommended_action']=='run_collect_or_check_controller' and watched['last_activity_age_seconds'] >= hs_watch['watchdog']['stale_dispatch_seconds'], watched
        assert any(r.get('id')=='harness_selfcheck_stale' for r in hs_watch['watchdog']['attention_runs']), hs_watch['watchdog']
        # ---- v0.24 follow-up manual harness resolution：只更新本地状态/审计字段，不触发外部工具或邮箱 ----
        manual=req('/api/harness/resolve', {
            'harness_run_id':'harness_selfcheck_stale',
            'status':'completed',
            'resolution_summary':'self-check operator manually closed a stale harness run',
            'next_action':'self-check manual resolution captured',
            'artifacts':['selfcheck://manual-resolution'],
            'external_side_effects':[],
        })
        assert manual['ok'] and manual['result']['status']=='completed', manual
        st_manual=req('/api/state')
        manual_run=next((r for r in st_manual.get('harness_runs', []) if r.get('id')=='harness_selfcheck_stale'), None)
        assert manual_run and manual_run['status']=='completed', st_manual.get('harness_runs')
        assert manual_run.get('manual_resolution', {}).get('summary')=='self-check operator manually closed a stale harness run', manual_run
        assert manual_run.get('next_action')=='self-check manual resolution captured' and manual_run.get('artifacts')==['selfcheck://manual-resolution'], manual_run
        assert any(s.get('name')=='manual_resolution' and s.get('status')=='done' for s in manual_run.get('stages', [])), manual_run.get('stages')
        # ---- v0.24 follow-up harness recovery：collect 只读；retry 只创建确认门，不自动重发邮箱 ----
        st_for_recovery=json.loads(state.read_text(encoding='utf-8'))
        recover_run={
            'id':'harness_selfcheck_recover',
            'created_at':'2000-01-01T00:00:00+00:00',
            'updated_at':'2000-01-01T00:00:00+00:00',
            'source':'self_check',
            'return_channel':'ui',
            'input':'daemon 分神：self-check recover retry target',
            'route_type':'daemon_plan',
            'status':'stuck',
            'protocol':'intake -> route -> approval -> dispatch -> collect -> return',
            'stages':[{'name':'dispatch','status':'done','at':'2000-01-01T00:00:00+00:00'}],
            'artifacts':[],
            'risk_gates':[],
        }
        st_for_recovery.setdefault('harness_runs', []).insert(0, recover_run)
        before_recover_dispatches=len(st_for_recovery.get('lingtai_dispatches', []))
        state.write_text(json.dumps(st_for_recovery, ensure_ascii=False, indent=2), encoding='utf-8')
        recover_collect=req('/api/harness/recover', {'harness_run_id':'harness_selfcheck_recover', 'action':'collect'})
        assert recover_collect['ok'] and recover_collect['result']['action']=='collect' and recover_collect['result']['external_side_effects']==[], recover_collect
        st_recover_collect=req('/api/state')
        recover_run_after_collect=next((r for r in st_recover_collect.get('harness_runs', []) if r.get('id')=='harness_selfcheck_recover'), None)
        assert recover_run_after_collect and any(x.get('name')=='recovery_collect' for x in recover_run_after_collect.get('stages', [])), recover_run_after_collect
        assert len(st_recover_collect.get('lingtai_dispatches', []))==before_recover_dispatches, st_recover_collect.get('lingtai_dispatches')
        recover_retry=req('/api/harness/recover', {
            'harness_run_id':'harness_selfcheck_recover',
            'action':'request_retry',
            'retry_description':'daemon 分神：self-check recover retry target',
            'reason':'self-check asks for approval-gated retry',
        })
        assert recover_retry['ok'] and recover_retry['result']['action']=='request_retry', recover_retry
        assert recover_retry['result']['approval_id'] and recover_retry['result']['worker_request_id'], recover_retry
        assert recover_retry['result']['dispatches_created']==0 and recover_retry['result']['external_side_effects']==[], recover_retry
        st_recover_retry=req('/api/state')
        recover_run_after_retry=next((r for r in st_recover_retry.get('harness_runs', []) if r.get('id')=='harness_selfcheck_recover'), None)
        assert recover_run_after_retry and recover_run_after_retry['status']=='awaiting_approval', recover_run_after_retry
        assert any(x.get('name')=='recovery_retry' and x.get('status')=='pending' for x in recover_run_after_retry.get('stages', [])), recover_run_after_retry.get('stages')
        retry_wr=next((w for w in st_recover_retry.get('worker_requests', []) if w.get('id')==recover_retry['result']['worker_request_id']), None)
        assert retry_wr and retry_wr['status']=='awaiting_approval' and retry_wr.get('harness_run_id')=='harness_selfcheck_recover', retry_wr
        retry_ap=next((a for a in st_recover_retry.get('approvals', []) if a.get('id')==recover_retry['result']['approval_id']), None)
        assert retry_ap and retry_ap.get('action')=='worker_dispatch' and retry_ap.get('worker_harness_run_id')=='harness_selfcheck_recover', retry_ap
        assert len(st_recover_retry.get('lingtai_dispatches', []))==before_recover_dispatches, st_recover_retry.get('lingtai_dispatches')
        recover_retry_again=req('/api/harness/recover', {'harness_run_id':'harness_selfcheck_recover', 'action':'request_retry', 'retry_description':'should be rejected'})
        assert not recover_retry_again['ok'] and '等待确认' in recover_retry_again.get('error',''), recover_retry_again
        route_need_confirm=req('/api/task/route', {'text':'派发 worker-one 自检路由：需要先确认再写真实邮箱', 'source':'self_check'})
        assert route_need_confirm['ok'] and route_need_confirm['result']['route_type']=='lingtai_mailbox' and route_need_confirm['result']['status']=='needs_confirm_dispatch', route_need_confirm
        route_disp=req('/api/task/route', {'text':'派发 worker-one 自检路由：确认后写入真实 fake outbox', 'source':'self_check', 'confirm_dispatch': True})
        assert route_disp['ok'] and route_disp['result']['route_type']=='lingtai_mailbox' and route_disp['result']['status']=='dispatched', route_disp
        route_mailbox_id=route_disp['result']['mailbox_id']
        route_dispatch=next((d for d in req('/api/state').get('lingtai_dispatches', []) if d.get('mailbox_id')==route_mailbox_id), None)
        assert route_dispatch and pathlib.Path(route_dispatch['outbox_path']).joinpath('message.json').exists(), route_disp

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

        # ---- v0.23 受控 worker 调度：Task Router 只创建确认闸；批准后写真实内部邮箱给 controller，再按 worker_request_id 回收结果 ----
        worker_route=req('/api/task/route', {'text':'daemon 分神：请扫一遍 self-check worker 调度链路并总结', 'source':'self_check'})
        assert worker_route['ok'] and worker_route['result']['route_type']=='daemon_plan', worker_route
        assert worker_route['result']['status']=='awaiting_worker_dispatch_approval', worker_route
        wr_id=worker_route['result']['worker_request_id']
        ap_id=worker_route['result']['approval_id']
        harness_id=worker_route['result']['harness_run_id']
        st_worker=req('/api/state')
        wr=next((w for w in st_worker.get('worker_requests', []) if w.get('id')==wr_id), None)
        assert wr and wr['status']=='awaiting_approval' and wr['kind']=='daemon' and wr['controller']=='mimo-2-5-pro' and wr.get('harness_run_id')==harness_id, st_worker.get('worker_requests')
        hrun=next((h for h in st_worker.get('harness_runs', []) if h.get('id')==harness_id), None)
        assert hrun and hrun['status']=='awaiting_approval' and hrun.get('worker_request_id')==wr_id, st_worker.get('harness_runs')
        wap=next((a for a in st_worker.get('approvals', []) if a.get('id')==ap_id and a.get('action')=='worker_dispatch'), None)
        assert wap and wap.get('worker_request_id')==wr_id and wap.get('worker_kind')=='daemon' and wap.get('worker_harness_run_id')==harness_id, st_worker.get('approvals')
        worker_ok=req('/api/approval/approve', {'approval_id': ap_id})
        assert worker_ok['ok'], worker_ok
        st_worker2=req('/api/state')
        wr2=next(w for w in st_worker2.get('worker_requests', []) if w.get('id')==wr_id)
        assert wr2['status']=='dispatched_to_controller' and wr2.get('mailbox_id'), wr2
        wdisp=next((d for d in st_worker2.get('lingtai_dispatches', []) if d.get('worker_request_id')==wr_id), None)
        assert wdisp and wdisp['to']=='mimo-2-5-pro' and wdisp['status']=='queued_to_worker_controller', st_worker2.get('lingtai_dispatches')
        wmsg_path=pathlib.Path(wdisp['outbox_path'])/'message.json'
        assert wmsg_path.exists(), wdisp
        wmsg=json.loads(wmsg_path.read_text(encoding='utf-8'))
        assert wr_id in wmsg['message'] and harness_id in wmsg['message'] and 'HARNESS_REPLY_JSON' in wmsg['message'] and 'worker_request_id' in wmsg['message'] and wmsg['to']==['mimo-2-5-pro'], wmsg

        winbox=fake_network/'mimo-2-5-pro'/'mailbox'/'inbox'/'reply-worker-selfcheck-0001'
        winbox.mkdir(parents=True, exist_ok=True)
        (winbox/'message.json').write_text(json.dumps({
            '_mailbox_id':'reply-worker-selfcheck-0001',
            'from':'mimo-2-5-pro',
            'to':['mimo-2-5-pro'],
            'subject':'Re: '+wdisp['subject'],
            'message':'controller reply with structured result\n```json\n'+json.dumps({'worker_request_id':wr_id,'harness_run_id':harness_id,'status':'completed','summary':'daemon self-check harness result OK','artifacts':['selfcheck://worker', {'kind':'report','path':'selfcheck://report'}], 'next_action':'self-check next action captured', 'external_side_effects':[{'kind':'fake_network_mailbox','detail':'self-check only'}]}, ensure_ascii=False)+'\n```',
            'received_at':'2026-06-05T00:01:00Z',
        }, ensure_ascii=False), encoding='utf-8')
        wcoll=req('/api/lingtai/collect', {})
        assert wcoll['ok'] and wcoll['result']['collected']==1, wcoll
        st_worker3=req('/api/state')
        wr3=next(w for w in st_worker3.get('worker_requests', []) if w.get('id')==wr_id)
        assert wr3['status']=='completed' and wr3.get('reply_result_id') and 'controller_reply_collected' in wr3.get('steps', []), wr3
        assert wr3.get('structured_result', {}).get('summary')=='daemon self-check harness result OK', wr3
        assert wr3.get('next_action')=='self-check next action captured' and wr3.get('artifacts') and wr3.get('external_side_effects'), wr3
        hrun3=next((h for h in st_worker3.get('harness_runs', []) if h.get('id')==harness_id), None)
        assert hrun3 and hrun3['status']=='completed' and hrun3.get('structured_result', {}).get('status')=='completed', hrun3
        assert hrun3.get('next_action')=='self-check next action captured' and hrun3.get('has_external_side_effects') is True, hrun3
        result_row=next((r for r in st_worker3.get('lingtai_mail_results', []) if r.get('worker_request_id')==wr_id and r.get('worker_kind')=='daemon' and r.get('structured_result')), None)
        assert result_row and result_row.get('next_action')=='self-check next action captured' and result_row.get('external_side_effects'), st_worker3.get('lingtai_mail_results')

        # ---- v0.24 external_side_effects 回传确认门：有真实 WeChat return channel 时，先确认再进入 bridge outbox ----
        st_side=json.loads(state.read_text(encoding='utf-8'))
        side_harness_id='harness_selfcheck_side_effect_gate'
        side_wr_id='worker_selfcheck_side_effect_gate'
        side_dispatch_id='dispatch_selfcheck_side_effect_gate'
        st_side.setdefault('harness_runs', []).insert(0, {
            'id':side_harness_id,
            'created_at':'2026-06-05T00:02:00Z',
            'updated_at':'2026-06-05T00:02:00Z',
            'source':'self_check',
            'return_channel':'wechat',
            'input':'self-check side-effect gate run',
            'route_type':'daemon_plan',
            'status':'dispatched',
            'protocol':'intake -> route -> approval -> dispatch -> collect -> return',
            'stages':[{'name':'dispatch','status':'done','at':'2026-06-05T00:02:00Z'}],
            'artifacts':[],
            'risk_gates':[],
        })
        st_side.setdefault('worker_requests', []).insert(0, {
            'id':side_wr_id,
            'created_at':'2026-06-05T00:02:00Z',
            'kind':'daemon',
            'label':'Daemon',
            'status':'dispatched_to_controller',
            'controller':'mimo-2-5-pro',
            'description':'self-check side-effect gate worker',
            'source':'self_check',
            'route_id':'selfcheck-side-effect-route',
            'task_id':'',
            'agent_id':'',
            'inbound_id':'wx-selfcheck-side-effect',
            'user_id':'wx-selfcheck-user',
            'reply_to_message_id':'wx-selfcheck-msg',
            'harness_run_id':side_harness_id,
            'steps':['created','approval_required','dispatched_to_controller'],
        })
        st_side.setdefault('lingtai_dispatches', []).insert(0, {
            'id':side_dispatch_id,
            'mailbox_id':'mailbox-selfcheck-side-effect',
            'created_at':'2026-06-05T00:02:00Z',
            'status':'queued_to_worker_controller',
            'from':'human',
            'to':'mimo-2-5-pro',
            'subject':'Selfcheck side-effect gate dispatch',
            'message_preview':'self-check side-effect gate worker',
            'worker_request_id':side_wr_id,
            'worker_kind':'daemon',
            'harness_run_id':side_harness_id,
        })
        before_side_outbox=len(st_side.get('wechat_outbox', []))
        state.write_text(json.dumps(st_side, ensure_ascii=False, indent=2), encoding='utf-8')
        side_inbox=fake_network/'mimo-2-5-pro'/'mailbox'/'inbox'/'reply-side-effect-selfcheck-0001'
        side_inbox.mkdir(parents=True, exist_ok=True)
        (side_inbox/'message.json').write_text(json.dumps({
            '_mailbox_id':'reply-side-effect-selfcheck-0001',
            'from':'mimo-2-5-pro',
            'to':['mimo-2-5-pro'],
            'subject':'Re: Selfcheck side-effect gate dispatch',
            'message':'controller reply with side effects\n```json\n'+json.dumps({'worker_request_id':side_wr_id,'harness_run_id':side_harness_id,'status':'completed','summary':'side effect gate summary','artifacts':['selfcheck://side-effect'], 'next_action':'approve bridge return only after review', 'external_side_effects':[{'kind':'fake_external_post','detail':'self-check only'}]}, ensure_ascii=False)+'\n```',
            'received_at':'2026-06-05T00:02:30Z',
        }, ensure_ascii=False), encoding='utf-8')
        side_coll=req('/api/lingtai/collect', {})
        assert side_coll['ok'] and side_coll['result']['collected']==1, side_coll
        st_side2=req('/api/state')
        side_wr=next(w for w in st_side2.get('worker_requests', []) if w.get('id')==side_wr_id)
        assert side_wr['status']=='awaiting_side_effect_review' and side_wr.get('side_effect_review_id'), side_wr
        side_run=next(h for h in st_side2.get('harness_runs', []) if h.get('id')==side_harness_id)
        assert side_run['status']=='awaiting_side_effect_review' and side_run.get('side_effect_review_id')==side_wr.get('side_effect_review_id'), side_run
        side_review=next(r for r in st_side2.get('side_effect_reviews', []) if r.get('id')==side_wr.get('side_effect_review_id'))
        assert side_review['status']=='pending' and side_review.get('approval_id') and side_review.get('external_side_effects'), side_review
        hs_side=req('/api/harness/status')
        hs_side_review=next((r for r in hs_side.get('side_effect_reviews', []) if r.get('id')==side_review['id']), None)
        assert hs_side['ok'] and hs_side['counts']['pending_side_effect_reviews'] >= 1 and hs_side['counts']['awaiting_side_effect_review'] >= 1, hs_side
        assert hs_side_review and hs_side_review['status']=='pending' and hs_side_review.get('external_side_effects'), hs_side.get('side_effect_reviews')
        assert len(st_side2.get('wechat_outbox', []))==before_side_outbox, st_side2.get('wechat_outbox')
        side_ap=next(a for a in st_side2.get('approvals', []) if a.get('id')==side_review.get('approval_id'))
        assert side_ap['action']=='harness_side_effect_return' and side_ap.get('side_effect_review_id')==side_review['id'], side_ap
        side_ok=req('/api/approval/approve', {'approval_id': side_ap['id']})
        assert side_ok['ok'] and side_ok['result'].get('result', {}).get('outbox_id'), side_ok
        st_side3=req('/api/state')
        side_review_done=next(r for r in st_side3.get('side_effect_reviews', []) if r.get('id')==side_review['id'])
        assert side_review_done['status']=='approved_for_bridge' and side_review_done.get('outbox_id'), side_review_done
        hs_side_done=req('/api/harness/status')
        hs_side_review_done=next((r for r in hs_side_done.get('side_effect_reviews', []) if r.get('id')==side_review['id']), None)
        assert hs_side_review_done and hs_side_review_done['status']=='approved_for_bridge' and hs_side_review_done.get('outbox_id'), hs_side_done.get('side_effect_reviews')
        side_run_done=next(h for h in st_side3.get('harness_runs', []) if h.get('id')==side_harness_id)
        assert side_run_done['status']=='completed' and side_run_done.get('side_effect_review_status')=='approved_for_bridge', side_run_done
        side_out=next((o for o in st_side3.get('wechat_outbox', []) if o.get('id')==side_review_done.get('outbox_id')), None)
        assert side_out and side_out['status']=='ready_for_bridge' and 'side effect gate summary' in side_out.get('reply_text',''), side_out

        # ---- v0.24 GUI 真实 Worker 启动器：请求先入确认队列；daemon 批准后写真实 controller mailbox ----
        codex_no_cost=req('/api/worker/launcher/request', {'kind':'codex','description':'self-check: should be refused without confirm_cost'})
        assert not codex_no_cost['ok'] and '费用确认' in (codex_no_cost.get('error') or ''), codex_no_cost
        wl_req=req('/api/worker/launcher/request', {'kind':'daemon','description':'self-check GUI worker launcher daemon request','controller':'mimo-2-5-pro'})
        assert wl_req['ok'] and wl_req['result']['status']=='awaiting_approval', wl_req
        wl_id=wl_req['result']['launch_id']; wl_ap=wl_req['result']['approval_id']
        st_wl=req('/api/state')
        wl=next((x for x in st_wl.get('worker_launches', []) if x.get('id')==wl_id), None)
        assert wl and wl['kind']=='daemon' and wl['status']=='awaiting_approval' and wl['approval_id']==wl_ap, st_wl.get('worker_launches')
        wl_ap_obj=next((a for a in st_wl.get('approvals', []) if a.get('id')==wl_ap and a.get('action')=='worker_launch'), None)
        assert wl_ap_obj and wl_ap_obj.get('worker_launch_id')==wl_id, st_wl.get('approvals')
        wl_ok=req('/api/approval/approve', {'approval_id': wl_ap})
        assert wl_ok['ok'], wl_ok
        st_wl2=req('/api/state')
        wl2=next(x for x in st_wl2.get('worker_launches', []) if x.get('id')==wl_id)
        assert wl2['status']=='dispatched_to_controller' and wl2.get('mailbox_id') and wl2.get('worker_request_id'), wl2
        wl_disp=next((d for d in st_wl2.get('lingtai_dispatches', []) if d.get('mailbox_id')==wl2.get('mailbox_id')), None)
        assert wl_disp and pathlib.Path(wl_disp['outbox_path']).joinpath('message.json').exists(), wl_disp

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
        assert 'Yuan Nutrition MAS Harness v0.24' in wx['result']['reply_text'], wx
        out_id=wx['result']['outbox']['id']
        sent=req('/api/wechat/bridge/mark_sent', {'outbox_id':out_id,'sent_message_id':'sent_selfcheck_status'})
        assert sent['ok'] and sent['result']['status']=='sent', sent
        wx2=req('/api/wechat/bridge/incoming', {'text':'请帮我记录一个普通任务','user_id':'wx_selfcheck','message_id':'msg_selfcheck_task','sender':'圆酱'})
        assert wx2['ok'] and '任务队列' in wx2['result']['reply_text'], wx2
        assert wx2['result']['inbound'].get('route_id'), wx2
        pending=req('/api/wechat/bridge/pending', {'limit': 10})
        assert pending['ok'] and pending['result']['runner_contract']=='no_second_poller' and pending['result']['count'] >= 1, pending
        pending_out_id=wx2['result']['outbox']['id']
        sent2=req('/api/wechat/bridge/mark_sent', {'outbox_id':pending_out_id,'sent_message_id':'sent_selfcheck_task'})
        assert sent2['ok'] and sent2['result']['status']=='sent', sent2
        st=req('/api/state')
        assert st['wechat_bridge']['status']=='ready' and len(st.get('wechat_outbox', []))>=2, st
        assert st.get('router_runs') and any(r.get('id')==wx2['result']['inbound'].get('route_id') for r in st['router_runs']), st.get('router_runs')

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

        # ---- v0.23 WeChat 来源的 worker 调度：确认后回收 controller 回信，并进入 no_second_poller outbox ----
        wx_worker=req('/api/wechat/bridge/incoming', {
            'text':'daemon 分神 帮我检查微信来源 worker 汇总链路',
            'user_id':'wx_selfcheck','message_id':'msg_selfcheck_worker','sender':'圆酱'})
        assert wx_worker['ok'] and wx_worker['result']['inbound'].get('route_id'), wx_worker
        wx_route_id=wx_worker['result']['inbound']['route_id']
        st_wxw=req('/api/state')
        wx_wr=next((w for w in st_wxw.get('worker_requests', []) if w.get('route_id')==wx_route_id), None)
        assert wx_wr and wx_wr['status']=='awaiting_approval' and wx_wr.get('user_id')=='wx_selfcheck' and wx_wr.get('reply_to_message_id')=='msg_selfcheck_worker', st_wxw.get('worker_requests')
        wx_ap=next((a for a in st_wxw.get('approvals', []) if a.get('action')=='worker_dispatch' and a.get('worker_request_id')==wx_wr['id']), None)
        assert wx_ap, st_wxw.get('approvals')
        wx_worker_ok=req('/api/approval/approve', {'approval_id': wx_ap['id']})
        assert wx_worker_ok['ok'], wx_worker_ok
        st_wxw2=req('/api/state')
        wx_disp=next((d for d in st_wxw2.get('lingtai_dispatches', []) if d.get('worker_request_id')==wx_wr['id']), None)
        assert wx_disp and pathlib.Path(wx_disp['outbox_path']).joinpath('message.json').exists(), wx_disp
        wx_inbox=fake_network/'mimo-2-5-pro'/'mailbox'/'inbox'/'reply-worker-selfcheck-wechat'
        wx_inbox.mkdir(parents=True, exist_ok=True)
        (wx_inbox/'message.json').write_text(json.dumps({
            '_mailbox_id':'reply-worker-selfcheck-wechat',
            'from':'mimo-2-5-pro',
            'to':['mimo-2-5-pro'],
            'subject':'Re: '+wx_disp['subject'],
            'message':'controller reply: worker_request_id '+wx_wr['id']+' 微信来源 worker 已完成。',
            'received_at':'2026-06-05T00:02:00Z',
        }, ensure_ascii=False), encoding='utf-8')
        wx_coll=req('/api/lingtai/collect', {})
        assert wx_coll['ok'] and wx_coll['result']['collected']==1, wx_coll
        st_wxw3=req('/api/state')
        wx_wr_done=next(w for w in st_wxw3.get('worker_requests', []) if w.get('id')==wx_wr['id'])
        assert wx_wr_done['status']=='reply_received', wx_wr_done
        wx_pending=req('/api/wechat/bridge/pending', {'limit': 20})
        assert wx_pending['ok'] and any(o.get('reply_to_message_id')=='msg_selfcheck_worker' and '受控 worker 调度已回收' in o.get('reply_text','') for o in wx_pending['result']['pending']), wx_pending

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
        print('OK Yuan Nutrition MAS Harness v0.24 self-check passed')
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
        # 清理可能残留的 Keychain 假 key（隔离 service）与受限 fallback 文件。
        if have_security:
            subprocess.run(['security','delete-generic-password','-a','openai','-s',KC_SERVICE], capture_output=True)
            subprocess.run(['security','delete-generic-password','-a','glm','-s',KC_SERVICE], capture_output=True)
        shutil.rmtree(ROOT/'.secrets', ignore_errors=True)
if __name__ == '__main__': main()
