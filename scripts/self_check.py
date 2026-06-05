#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LingTai Simple v0.2 本地自检：启动临时 server，验证 GUI/API/脱敏/确认队列。"""
import json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error
ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = int(os.environ.get('LINGTAI_SIMPLE_TEST_PORT', '8799'))
BASE = f'http://127.0.0.1:{PORT}'

def req(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    r = urllib.request.Request(BASE + path, data=data, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r, timeout=5) as resp:
        body = resp.read()
    try: return json.loads(body.decode('utf-8'))
    except Exception: return body.decode('utf-8', errors='replace')

def main():
    state = ROOT/'data'/'state.json'
    if state.exists(): state.unlink()
    proc = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env={**os.environ, 'LINGTAI_SIMPLE_PORT': str(PORT)}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        time.sleep(1.0)
        assert '圆酱' in req('/')
        health=req('/api/health'); assert health['ok'], health
        catalog=req('/api/catalog'); assert len(catalog['providers'])>=6 and catalog['max_agents']==5
        r=req('/api/provider/save', {'provider_id':'openai','base_url':'https://api.example.invalid/v1','model':'gpt-test','api_key':'sk-v0-2-secret-ABCDEFGH','key_label':'selfcheck'})
        assert r['ok'] and r['result']['key_last4']=='EFGH' and 'api_key' not in r['result']
        assert 'sk-v0-2-secret-ABCDEFGH' not in (state.read_text(encoding='utf-8') if state.exists() else '')
        a=req('/api/agent/create', {'name':'自检灵','role':'长期助手','provider_id':'openai','cc_level':'L1'})
        aid=a['result']['id']
        low=req('/api/task/assign', {'agent_id':aid,'description':'只读整理','risk':'low'}); assert low['result']['status']=='完成'
        hi=req('/api/task/assign', {'agent_id':aid,'description':'merge PR','risk':'sensitive'}); assert hi['result']['status']=='等确认'
        demo=req('/api/demo/load', {}); assert demo['ok'] and demo['result']['agents'] >= 1
        sg=req('/api/shougong', {}); assert pathlib.Path(sg['result']['path']).exists()
        print('OK LingTai Simple v0.2 self-check passed')
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()
        if state.exists(): state.unlink()
if __name__ == '__main__': main()
