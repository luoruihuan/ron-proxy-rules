#!/usr/bin/env python3
"""住宅精选订阅服务（VM 版 v2）

职责：
  1. 定时巡检候选落地 IP，只输出「稳定的前 N 个」
  2. 把每个节点的 dialer-proxy 改写为自建前置（Hy2-vm2-main）
  3. 上游订阅结构变动时能自动跟随，出问题时不会静默返回坏数据

v2 相对 v1 的修正：
  - 巡检成本：原来每 30 分钟给 18 个 IP 各下 3MB，一天烧 2.6GB 代理流量。
    现在改为「轻量存活探测（~1KB）每 30 分钟 + 全量测速每 12 小时且只测前 8 个」。
  - 输出只保留 proxies 段，去掉 proxy-groups 和 rules，避免把客户端全局流量误导向住宅链。
  - 上游新增节点自动纳入（按 ASN 自动分档），不再依赖硬编码候选池。
  - 上游拉取失败时用上一次的缓存兜底；精选为空时明确报错，不返回空订阅。
  - 速度多次采样取最优值，避免瞬时抖动误杀好节点。
"""

import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, 'config.json')
STATE_PATH = os.path.join(BASE, 'state.json')
LAST_GOOD = os.path.join(BASE, 'last_good.yaml')

DEFAULTS = {
    "upstream": "",
    "chain_node": "Hy2-vm2-main",
    "top_n": 5,
    # 候选池：留空=全部自动纳入。填了则只在这些编号里选（顺序=同档位时的优先）
    "pool": [
        "静态12", "静态38",
        "静态13", "静态14", "静态20", "静态23", "静态24", "静态37", "静态40", "静态46",
        "静态02", "静态04", "静态01", "静态03", "静态07",
    ],
    # 自动分档：ASN 关键字 -> 住宅档位（1 最纯）
    "tier_by_asn": {
        "RingSquared": 1,
        "RCN": 2,
    },
    "default_tier": 3,
    # 手动指定档位（覆盖 ASN 自动判定）
    "tier": {
        "静态12": 1, "静态38": 1,
        "静态13": 2, "静态14": 2, "静态20": 2, "静态23": 2,
        "静态24": 2, "静态37": 2, "静态40": 2, "静态46": 2,
    },
    "risk_cache_hours": 6,
    # 存活探测间隔（轻量，几乎不耗流量）
    "recheck_minutes": 30,
    # 全量测速间隔（较耗流量，别调太小）
    "speed_minutes": 720,
    "speed_candidates": 8,
    "probe_bytes": 1000000,
    "speed_samples": 2,
    "port": 8791,
    "path_token": "",
    # 飞书机器人 webhook（卡片告警）
    "feishu_webhook": "",
    # 连续失败多少次算异常
    "alert_fail_threshold": 2,
    # 同类告警最小间隔（分钟），防刷屏
    "alert_cooldown_minutes": 120,
    # 告警卡片底部按钮指向的状态页（可选，留空则不加）
    "status_url": "",
}


# ---------------------------------------------------------------- 基础工具
def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg.update(load_json(CONFIG_PATH))
    if not cfg.get('path_token'):
        cfg['path_token'] = os.urandom(12).hex()
        save_json(CONFIG_PATH, cfg)
    return cfg


def curl(args, timeout):
    """统一封装 curl 调用，避免各处参数漂移"""
    try:
        p = subprocess.run(['curl', '-s', '--noproxy', ''] + args,
                           capture_output=True, timeout=timeout)
        return p.stdout.decode('utf-8', 'ignore').strip()
    except Exception:
        return ''


# ---------------------------------------------------------------- 订阅解析
def fetch_upstream(url, timeout=30):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={'User-Agent': 'ClashforWindows/0.20.39'})
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def parse_statics(yaml_text):
    """从上游 Clash yaml 抽静态住宅节点。结构不符合预期时返回 {}（由调用方判断）"""
    if 'proxies:' not in yaml_text:
        return {}
    sec = yaml_text.split('proxies:', 1)[1]
    sec = sec.split('proxy-groups:', 1)[0] if 'proxy-groups:' in sec else sec
    out = {}
    for block in re.split(r'\n- ', '\n' + sec.strip()):
        m = re.search(r'name:\s*(.+)', block)
        if not m:
            continue
        name = m.group(1).strip().strip("'\"")
        num = re.search(r'静态\s*(\d+)', name)
        if not num:
            continue

        def g(k):
            mm = re.search(r'(?m)^\s*' + k + r':\s*(\S+)\s*$', block)
            return mm.group(1) if mm else ''

        key = f'静态{int(num.group(1)):02d}'
        out[key] = {
            'name': name, 'num': key,
            'type': g('type') or 'http',
            'server': g('server'), 'port': g('port'),
            'username': g('username'), 'password': g('password'),
        }
    return out


def node_ip(node):
    m = re.search(r'ip-(\d+\.\d+\.\d+\.\d+)', node['username'])
    return m.group(1) if m else ''


# ---------------------------------------------------------------- 探测
def liveness(node, timeout=18):
    """轻量存活探测：只取几百字节，几乎不耗代理流量"""
    proxy = f"http://{node['username']}:{node['password']}@{node['server']}:{node['port']}"
    out = curl(['-x', proxy, '-o', '/dev/null', '-m', str(timeout),
                '-w', '%{http_code}|%{time_starttransfer}', 'https://ipinfo.io/json'],
               timeout + 8)
    if not out or '|' not in out:
        return {'ok': False, 'ttfb': None, 'reason': 'connect-fail'}
    code, ttfb = (out.split('|') + [''])[:2]
    ok = code == '200'
    return {'ok': ok, 'ttfb': float(ttfb or 0) if ok else None,
            'reason': '' if ok else f'http-{code}'}


def speed_probe(node, cfg):
    """带宽采样：下载 probe_bytes，多次取最优（避免瞬时抖动误杀）"""
    proxy = f"http://{node['username']}:{node['password']}@{node['server']}:{node['port']}"
    best = 0.0
    ttfb = None
    for _ in range(max(1, int(cfg['speed_samples']))):
        out = curl(['-x', proxy, '-o', '/dev/null', '-m', '30',
                    '-w', '%{speed_download}|%{time_starttransfer}',
                    f"https://speed.cloudflare.com/__down?bytes={cfg['probe_bytes']}"],
                   40)
        if not out or '|' not in out:
            continue
        sp, t = (out.split('|') + [''])[:2]
        try:
            sp = float(sp or 0)
        except ValueError:
            sp = 0
        if sp > best:
            best = sp
        if t and ttfb is None:
            ttfb = float(t)
    return {'speed': best, 'ttfb': ttfb, 'measured': bool(best)}


def risk_lookup(node):
    """公开库画像：机房/代理标记 + ASN（用于自动分档）"""
    ip = node_ip(node)
    if not ip:
        return {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        u = f'http://ip-api.com/json/{ip}?fields=status,isp,org,as,proxy,hosting,mobile'
        with opener.open(u, timeout=10) as r:
            d = json.loads(r.read().decode())
        return d if d.get('status') == 'success' else {}
    except Exception:
        return {}


def refresh_risk(cfg, nodes, nums, state):
    cache = state.get('risk') or {}
    now = time.time()
    fresh, stale = {}, []
    for num in nums:
        item = cache.get(num)
        if item and now - item.get('ts', 0) < cfg['risk_cache_hours'] * 3600:
            fresh[num] = item['data']
        else:
            stale.append(num)
    if stale:
        with ThreadPoolExecutor(max_workers=4) as ex:
            got = dict(zip(stale, ex.map(lambda k: risk_lookup(nodes[k]), stale)))
        for num, data in got.items():
            fresh[num] = data
            cache[num] = {'ts': now, 'data': data}
        state['risk'] = cache
    return fresh


def tier_of(cfg, num, risk):
    if num in cfg['tier']:
        return cfg['tier'][num]
    asn = ' '.join([str(risk.get('as') or ''), str(risk.get('isp') or ''),
                    str(risk.get('org') or '')])
    for kw, t in cfg['tier_by_asn'].items():
        if kw.lower() in asn.lower():
            return t
    return cfg['default_tier']


# ---------------------------------------------------------------- 排名
def rank(cfg, nodes, state):
    # 候选：配置池 ∩ 上游现有节点；池内没列到的也自动纳入（上限 pool + 6）
    pool = [p for p in cfg['pool'] if p in nodes]
    extra = [n for n in sorted(nodes) if n not in pool][:6]
    candidates = pool + extra
    if not candidates:
        return []

    prev = [n for n in state.get('selected', []) if n in nodes]

    # 1) 轻量存活探测
    with ThreadPoolExecutor(max_workers=8) as ex:
        live = dict(zip(candidates, ex.map(lambda k: liveness(nodes[k]), candidates)))
    alive = [n for n in candidates if live[n]['ok']]

    # 2) 风险画像（含 ASN，用于自动分档）
    risks = refresh_risk(cfg, nodes, candidates, state)

    # 3) 带宽采样：只在过期时做，且只测档位靠前的少数几个
    scache = state.get('speed') or {}
    now = time.time()
    need = [n for n in alive
            if now - (scache.get(n, {}).get('ts', 0)) > cfg['speed_minutes'] * 60]
    need.sort(key=lambda n: (tier_of(cfg, n, risks.get(n, {})),
                             candidates.index(n)))
    need = need[:cfg['speed_candidates']]
    for n in need:
        sp = speed_probe(nodes[n], cfg)
        scache[n] = {'ts': now, **sp}
    state['speed'] = scache

    # 4) 打分
    scored = []
    for num in alive:
        risk = risks.get(num, {})
        if risk.get('hosting') or risk.get('proxy'):
            state.setdefault('excluded_flag', {})[num] = {
                'hosting': bool(risk.get('hosting')), 'proxy': bool(risk.get('proxy')),
                'isp': risk.get('isp') or risk.get('as') or ''}
            continue
        tier = tier_of(cfg, num, risk)
        sp = scache.get(num, {})
        speed = sp.get('speed', 0) or 0
        ttfb = sp.get('ttfb') or live[num]['ttfb'] or 0
        score = 100.0 - (tier - 1) * 18
        score -= candidates.index(num) * 1.2
        score += min(speed / 2_000_000, 1.0) * 25
        if ttfb:
            score += max(0, 1 - min(ttfb, 5) / 5) * 15
        scored.append({'num': num, 'tier': tier, 'score': round(score, 1),
                       'speed': speed, 'ttfb': ttfb, 'risk': risk,
                       'speed_age_min': round((now - sp.get('ts', 0)) / 60) if sp else None})

    scored.sort(key=lambda x: -x['score'])
    by_num = {s['num']: s for s in scored}

    # 5) 稳定优先：老名单活着就不换，缺口再补
    selected = [n for n in prev if n in by_num][:cfg['top_n']]
    for s in scored:
        if len(selected) >= cfg['top_n']:
            break
        if s['num'] not in selected:
            selected.append(s['num'])

    state['selected'] = selected
    state['ranking'] = [
        {'num': s['num'], 'tier': s['tier'], 'score': s['score'],
         'isp': s['risk'].get('isp') or s['risk'].get('as') or '',
         'speed_kbps': round(s['speed'] / 1024),
         'ttfb_ms': round(s['ttfb'] * 1000),
         'speed_age_min': s['speed_age_min'],
         'picked': s['num'] in selected}
        for s in scored]
    state['dead'] = [{'num': n, 'reason': live[n]['reason']}
                     for n in candidates if not live[n]['ok']]
    state['candidates'] = candidates
    state['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    return selected


# ---------------------------------------------------------------- 飞书告警
def feishu_send(cfg, payload):
    """发送飞书卡片。返回 (ok, 说明)"""
    url = cfg.get('feishu_webhook') or ''
    if not url:
        return False, '未配置 webhook'
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8'})
        with opener.open(req, timeout=15) as r:
            body = json.loads(r.read().decode('utf-8', 'ignore') or '{}')
        code = body.get('code', body.get('StatusCode', -1))
        return code == 0, str(body)
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def alert_card(title, template, fields, detail, footer):
    """飞书交互卡片：header 色块 + 双列字段 + 正文 + 底注"""
    elements = [{
        'tag': 'div',
        'fields': [{'is_short': True,
                    'text': {'tag': 'lark_md', 'content': f'**{k}**\n{v}'}}
                   for k, v in fields],
    }]
    if detail:
        elements += [{'tag': 'hr'},
                     {'tag': 'div', 'text': {'tag': 'lark_md', 'content': detail}}]
    elements.append({'tag': 'note',
                     'elements': [{'tag': 'plain_text', 'content': footer}]})
    return {'msg_type': 'interactive',
            'card': {'config': {'wide_screen_mode': True},
                     'header': {'template': template,
                                'title': {'tag': 'plain_text', 'content': title}},
                     'elements': elements}}


def evaluate_status(cfg, state):
    """返回 (状态, 原因)。状态：ok / warn / error"""
    sel = state.get('selected') or []
    dead = [d['num'] for d in (state.get('dead') or [])]
    dead_sel = [n for n in sel if n in dead]
    fails = state.get('consecutive_failures', 0)

    if not state.get('upstream_ok', True):
        # 单次抽风不打扰，连续失败达到阈值才报错
        if fails >= cfg['alert_fail_threshold']:
            return 'error', f'无法拉取上游订阅（连续 {fails} 次）'
        return 'ok', ''
    if not sel:
        return 'error', '没有可用落地节点'
    if len(sel) < cfg['top_n']:
        return 'warn', f'入选只有 {len(sel)} 个，不足 {cfg["top_n"]} 个'
    if dead_sel:
        return 'warn', '入选节点探测失败: ' + ', '.join(dead_sel)
    return 'ok', ''


def maybe_alert(cfg, state, force=False):
    """只在状态变化时推送；异常持续存在则按 cooldown 重提醒一次"""
    status, reason = evaluate_status(cfg, state)
    prev = state.get('alert_status', 'ok')
    last_ts = state.get('alert_ts', 0)
    now = time.time()
    cooldown = cfg['alert_cooldown_minutes'] * 60

    should = force or status != prev
    if not should and status == 'error' and now - last_ts > cooldown:
        should = True
    if not should:
        return None

    sel = state.get('selected') or []
    ranking = state.get('ranking') or []
    pool = state.get('candidates') or []
    top = ' · '.join(f"{r['num']}({r['speed_kbps']}KB/s)"
                     for r in ranking if r['picked']) or '无'
    footer = f"住宅精选订阅 · ron-vm1 · {time.strftime('%Y-%m-%d %H:%M')}"

    if status == 'ok':
        payload = alert_card('✅ 住宅精选订阅 · 已恢复', 'green',
                             [('主体', 'ron-vm1 精选服务'),
                              ('入选', f'{len(sel)} 个'),
                              ('候选池', f'{len(pool)} 个'),
                              ('巡检时间', state.get('updated_at', '-'))],
                             f'当前入选：{top}', footer)
    else:
        tpl = 'red' if status == 'error' else 'orange'
        head = '❌ 住宅精选订阅 · 故障' if status == 'error' else '⚠️ 住宅精选订阅 · 异常'
        detail = [f'**原因**\n{reason}', f'**当前入选**\n{top}']
        bad = state.get('dead') or []
        if bad:
            detail.append('**探测失败**\n' + '\n'.join(
                f"- {d['num']}：{d['reason']}" for d in bad[:6]))
        payload = alert_card(head, tpl,
                             [('主体', 'ron-vm1 精选服务'),
                              ('入选', f'{len(sel)}/{cfg["top_n"]}'),
                              ('候选池', f'{len(pool)} 个'),
                              ('上游', '正常' if state.get('upstream_ok', True) else '失败')],
                             '\n'.join(detail), footer)

    ok, msg = feishu_send(cfg, payload)
    state['alert_status'] = status
    if ok:
        state['alert_ts'] = now
    print(f'[alert] 状态={status} 发送={"OK" if ok else "FAIL"} {msg}', flush=True)
    return ok


# ---------------------------------------------------------------- 输出
def build_yaml(cfg, nodes, selected):
    """只输出 proxies 段：不带 groups / rules，避免影响客户端原有分流"""
    lines = ['proxies:']
    for num in selected:
        n = nodes[num]
        lines += [f"- name: {n['name']}",
                  f"  type: {n['type']}",
                  f"  server: {n['server']}",
                  f"  port: {n['port']}",
                  f"  username: {n['username']}",
                  f"  password: {n['password']}",
                  f"  dialer-proxy: {cfg['chain_node']}"]
    return '\n'.join(lines) + '\n'


class Handler(BaseHTTPRequestHandler):
    cfg = None
    state = None
    lock = threading.Lock()

    def do_GET(self):
        path = self.path.split('?')[0].strip('/')
        token = self.cfg['path_token']
        if path not in (f'{token}/sub', f'{token}/status', token):
            self._send(404, 'text/plain; charset=utf-8', b'not found')
            return

        if path.endswith('/status') or path == token:
            self.state['upstream_ok'] = self.state.get('upstream_ok')
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(self.state, ensure_ascii=False, indent=1).encode())
            return

        try:
            try:
                raw = fetch_upstream(self.cfg['upstream'])
                with self.lock:
                    self.state['upstream_ok'] = True
                    self.state['consecutive_failures'] = 0
            except Exception as e:
                # 兜底：上游失败时用上一次成功的内容，避免客户端拿到空订阅
                print(f'[sub] 上游失败 {e}，使用缓存', flush=True)
                with self.lock:
                    self.state['upstream_ok'] = False
                    self.state['consecutive_failures'] = \
                        self.state.get('consecutive_failures', 0) + 1
                    maybe_alert(self.cfg, self.state)
                if not os.path.exists(LAST_GOOD):
                    raise
                raw = open(LAST_GOOD, encoding='utf-8').read()

            nodes = parse_statics(raw)
            if not nodes:
                raise RuntimeError('上游 yaml 结构变了，解析不到任何静态节点')

            with self.lock:
                selected = self.state.get('selected') or []
                if not selected or any(n not in nodes for n in selected):
                    selected = rank(self.cfg, nodes, self.state)
                save_json(STATE_PATH, self.state)

            if not selected:
                raise RuntimeError('没有可用落地节点（全部探测失败或全部被标记）')

            yaml_text = build_yaml(self.cfg, nodes, selected)
            with open(LAST_GOOD, 'w', encoding='utf-8') as f:
                f.write(yaml_text)
            self._send(200, 'text/yaml; charset=utf-8', yaml_text.encode())
        except Exception as e:
            print(f'[sub] 生成失败: {e}', flush=True)
            with self.lock:
                maybe_alert(self.cfg, self.state)
            self._send(502, 'text/plain; charset=utf-8', f'sub build failed: {e}'.encode())

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        print('%s - %s' % (self.address_string(), fmt % a), flush=True)


def background(cfg, state):
    while True:
        try:
            raw = fetch_upstream(cfg['upstream'])
            nodes = parse_statics(raw)
            if not nodes:
                print('[recheck] 上游解析为空，跳过本轮', flush=True)
                with Handler.lock:
                    state['consecutive_failures'] = state.get('consecutive_failures', 0) + 1
                    maybe_alert(cfg, state)
            else:
                with Handler.lock:
                    state['upstream_ok'] = True
                    state['consecutive_failures'] = 0
                    rank(cfg, nodes, state)
                    save_json(STATE_PATH, state)
                    maybe_alert(cfg, state)
                print('[recheck]', state['selected'], flush=True)
        except Exception as e:
            print('[recheck] 失败:', e, flush=True)
            with Handler.lock:
                state['upstream_ok'] = False
                state['consecutive_failures'] = state.get('consecutive_failures', 0) + 1
                maybe_alert(cfg, state)
        time.sleep(cfg['recheck_minutes'] * 60)


def self_test_alert(cfg, state):
    """发送一张测试卡片，验证 webhook 通路"""
    payload = alert_card('🧪 住宅精选订阅 · 测试消息', 'blue',
                         [('主体', 'ron-vm1 精选服务'), ('状态', '告警通道正常'),
                          ('入选', f"{len(state.get('selected') or [])} 个"),
                          ('巡检时间', state.get('updated_at', '-'))],
                         '这是一条测试通知。以后只有出现异常或恢复时才会自动推送。',
                         f"住宅精选订阅 · ron-vm1 · {time.strftime('%Y-%m-%d %H:%M')}")
    ok, msg = feishu_send(cfg, payload)
    print(('✅ 推送成功' if ok else '❌ 推送失败'), msg)
    return ok


def main():
    cfg = load_config()
    state = load_json(STATE_PATH, {'selected': [], 'ranking': [], 'dead': [],
                                   'updated_at': '', 'speed': {}, 'risk': {}})

    if '-t' in os.sys.argv or '--test-alert' in os.sys.argv:
        raise SystemExit(0 if self_test_alert(cfg, state) else 1)
    if '--check-alert' in os.sys.argv:
        maybe_alert(cfg, state, force=True)
        raise SystemExit(0)

    Handler.cfg, Handler.state = cfg, state
    threading.Thread(target=background, args=(cfg, state), daemon=True).start()
    srv = ThreadingHTTPServer(('0.0.0.0', cfg['port']), Handler)
    print(f"v2 已启动 端口={cfg['port']} token={cfg['path_token']}"
          f" 告警={'开' if cfg.get('feishu_webhook') else '关'}", flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()