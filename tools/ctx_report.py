#!/usr/bin/env python3
"""把 QQ 四间会话的上下文曲线画成一页 HTML。

数据来自 magpie 的路由日志 ~/.config/magpie/routing/*.jsonl(.gz)：
每次请求都带 `prompt`（tokens / window / parts），parts 里能拆出
system / tools / chat / results 各占多少 —— 所以这页不只是「多大」，
还能看出「是谁吃掉的」。

用法：
    python3 tools/ctx_report.py                 # 近 7 天
    python3 tools/ctx_report.py --days 2
    python3 tools/ctx_report.py --out /tmp/x.html

会话名用 私聊 / 群甲 / 群乙 / 群丙（按桥配置里的绑定顺序），不写真实群号。
⚠ 小于 8k 的调用（记忆抽取那类辅助调用）不算进曲线，页脚注明了。
"""
import argparse
import datetime
import glob
import gzip
import json
import os
import statistics
import sys
from collections import defaultdict

ROUTING = os.path.expanduser('~/.config/magpie/routing')
CONFIG = os.path.expanduser('~/.dsh/qq-bridge-config.json')
OUT = os.path.expanduser('~/.dsh/ctx-report.html')

# 压缩参数生效的时刻（本地时间）—— 11-04 21:39 重启后生效
CHANGE_AT = datetime.datetime(2026, 11, 4, 21, 39).timestamp()

中文序号 = ['甲', '乙', '丙', '丁', '戊']


def 会话表():
    """session-xxx → 显示名。私聊排第一，群按绑定顺序叫甲乙丙。"""
    try:
        j = json.load(open(CONFIG, encoding='utf-8'))
    except Exception:
        return {}
    表, 群数 = {}, 0
    for b in j.get('绑定') or []:
        s = str(b.get('会话') or '').strip()
        if not s:
            continue
        if b.get('类型') == '私聊':
            表[s] = '私聊'
        else:
            表[s] = '群' + 中文序号[群数] if 群数 < len(中文序号) else '群%d' % 群数
            群数 += 1
    return 表


def 读一天(路径):
    try:
        fh = gzip.open(路径, 'rt', encoding='utf-8', errors='ignore') if 路径.endswith('.gz') \
            else open(路径, encoding='utf-8', errors='ignore')
    except OSError:
        return []
    out = []
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            out.append(r)
    return out


def 收数据(天数):
    表 = 会话表()
    今天 = datetime.date.today()
    点, 跳过 = [], 0
    for i in range(天数):
        d = 今天 - datetime.timedelta(days=i)
        for 路径 in (os.path.join(ROUTING, d.isoformat() + '.jsonl'),
                   os.path.join(ROUTING, d.isoformat() + '.jsonl.gz')):
            if not os.path.exists(路径):
                continue
            for r in 读一天(路径):
                s = str(r.get('session') or '')
                if s not in 表:
                    continue
                p = r.get('prompt') or {}
                toks = p.get('tokens')
                if not isinstance(toks, (int, float)):
                    continue
                if toks < 8000:      # 辅助调用（记忆抽取等）不算主回合
                    跳过 += 1
                    continue
                parts = {x.get('kind'): x.get('tokens') or 0 for x in (p.get('parts') or [])}
                合 = sum(parts.get(k, 0) for k in ('system', 'tools', 'skills', 'files', 'results', 'chat'))
                点.append({
                    't': int(datetime.datetime.fromisoformat(r['time'].replace('Z', '+00:00')).timestamp() * 1000)
                         if r.get('time') else 0,
                    'who': 表[s],
                    'model': r.get('model') or '',
                    'tok': int(toks),
                    'win': int(p.get('window') or 0),
                    'sys': int(parts.get('system', 0)),
                    'tools': int(parts.get('tools', 0)),
                    'chat': int(parts.get('chat', 0)),
                    'res': int(parts.get('results', 0)) + int(parts.get('files', 0)),
                    'other': max(0, int(toks) - 合),
                })
            break
    点 = [x for x in 点 if x['t']]
    点.sort(key=lambda x: x['t'])
    return 点, 跳过, 表


def 统计(点, 表):
    by = defaultdict(list)
    for x in 点:
        by[x['who']].append(x)
    统计们 = []
    for who in 表.values():
        xs = by.get(who) or []
        if not xs:
            continue
        v = [x['tok'] for x in xs]
        压 = 0
        for a, b in zip(xs, xs[1:]):
            if b['tok'] < a['tok'] * 0.7 and a['tok'] - b['tok'] > 10000:
                压 += 1
        统计们.append({
            'who': who, 'n': len(xs),
            'median': int(statistics.median(v)),
            'p90': sorted(v)[int(len(v) * 0.9)],
            'max': max(v),
            'last': xs[-1]['tok'],
            'win': xs[-1]['win'],
            'model': xs[-1]['model'],
            'compactions': 压,
            'latest': xs[-1],
        })
    return 统计们


def 画页(点, 统计们, 跳过, 天数):
    生成 = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    数据 = {
        'points': 点,
        'changeAt': int(CHANGE_AT * 1000),
        'stats': [{k: v for k, v in s.items() if k != 'latest'} for s in 统计们],
        'latest': {s['who']: s['latest'] for s in 统计们},
        'skipped': 跳过,
        'days': 天数,
        'generated': 生成,
    }
    return 模板.replace('__DATA__', json.dumps(数据, ensure_ascii=False))


模板 = r'''<title>小肥鱼上下文曲线</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --bg:#f6f5f0; --surface:#fdfcf9; --ink:#16150f; --ink-2:#5c594f; --ink-3:#8a8679;
  --line:#e2ded2; --grid:#e9e5d9;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --mark:#c8452f; --chip:#efeadc;
  --r:10px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#141411; --surface:#1b1b18; --ink:#f1efe9; --ink-2:#bdb9ad; --ink-3:#8e8a7e;
    --line:#2e2d27; --grid:#262520;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
    --mark:#e66767; --chip:#26251f;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#141411; --surface:#1b1b18; --ink:#f1efe9; --ink-2:#bdb9ad; --ink-3:#8e8a7e;
  --line:#2e2d27; --grid:#262520;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --mark:#e66767; --chip:#26251f;
  color-scheme: dark;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"IBM Plex Sans","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
  font-size:15px; line-height:1.6;
  padding-left:max(16px, env(safe-area-inset-left, 0px));
  padding-right:max(16px, env(safe-area-inset-right, 0px));
  padding-block:32px 56px;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1040px; margin:0 auto; display:flex; flex-direction:column; gap:28px}
header{display:flex; flex-direction:column; gap:6px}
h1{font-size:26px; line-height:1.25; margin:0; letter-spacing:-0.01em; font-weight:600; text-wrap:balance}
.sub{color:var(--ink-2); margin:0; max-width:62ch}
.meta{color:var(--ink-3); font-size:12.5px; font-variant-numeric:tabular-nums}

.tiles{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px}
.tile{background:var(--surface); border:1px solid var(--line); border-radius:var(--r); padding:14px 16px; display:flex; flex-direction:column; gap:2px}
.tile .k{font-size:12px; color:var(--ink-2); letter-spacing:.04em}
.tile .v{font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; letter-spacing:-0.02em}
.tile .u{font-size:11.5px; color:var(--ink-3)}

section{background:var(--surface); border:1px solid var(--line); border-radius:var(--r); padding:18px 18px 14px; display:flex; flex-direction:column; gap:10px; min-width:0}
section h2{font-size:14px; margin:0; font-weight:600; letter-spacing:.02em}
section .hint{font-size:12.5px; color:var(--ink-2); margin:0}
.controls{display:flex; gap:6px; flex-wrap:wrap; align-items:center}
button.range{
  font:inherit; font-size:12.5px; padding:4px 10px; border-radius:999px; cursor:pointer;
  border:1px solid var(--line); background:transparent; color:var(--ink-2);
}
button.range[aria-pressed="true"]{background:var(--chip); color:var(--ink); border-color:var(--line)}
button.range:focus-visible, .legend button:focus-visible{outline:2px solid var(--s1); outline-offset:2px}

.chart{position:relative; width:100%}
svg{display:block; width:100%; height:auto; overflow:visible}
.grid line{stroke:var(--grid); stroke-width:1}
.axis text{fill:var(--ink-3); font-size:11px; font-variant-numeric:tabular-nums}
.series{fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round}
.drop{stroke:var(--surface); stroke-width:2}
.changerule{stroke:var(--mark); stroke-width:1.5; stroke-dasharray:4 4; opacity:.75}
.changelabel{fill:var(--mark); font-size:11px}
.crosshair{stroke:var(--ink-3); stroke-width:1; opacity:.5}
.tip{
  position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font-size:12px; line-height:1.45; color:var(--ink);
  box-shadow:0 6px 20px rgba(0,0,0,.10); min-width:150px; display:none; z-index:3;
  font-variant-numeric:tabular-nums;
}
.tip b{font-weight:600}
.tip .row{display:flex; gap:8px; justify-content:space-between}
.tip .dot{width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:6px}

.legend{display:flex; gap:14px; flex-wrap:wrap; font-size:12.5px; color:var(--ink-2)}
.legend span{display:inline-flex; align-items:center; gap:6px}
.legend i{width:10px; height:10px; border-radius:2px; display:inline-block}

.bars{display:flex; flex-direction:column; gap:12px}
.bar-row{display:grid; grid-template-columns:64px minmax(0,1fr); gap:10px; align-items:center}
.bar-name{font-size:12.5px; color:var(--ink-2)}
.bar{display:flex; height:26px; border-radius:4px; overflow:hidden; gap:2px; background:var(--grid)}
.bar div{display:flex; align-items:center; justify-content:center; font-size:11px; color:#fff; white-space:nowrap; overflow:hidden}
.bar-legend{display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--ink-2); margin-top:2px}
.bar-legend span{display:inline-flex; align-items:center; gap:6px}
.bar-legend i{width:10px; height:10px; border-radius:2px}

table{width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums}
th,td{text-align:right; padding:7px 8px; border-bottom:1px solid var(--line)}
th:first-child, td:first-child{text-align:left}
thead th{color:var(--ink-3); font-weight:500; font-size:12px; letter-spacing:.03em}
tbody tr:last-child td{border-bottom:none}
.tw{overflow-x:auto}

footer{color:var(--ink-3); font-size:12px; line-height:1.7}
footer code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11.5px; background:var(--chip); padding:1px 5px; border-radius:4px}
@media (max-width:720px){
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
  .bar-row{grid-template-columns:52px minmax(0,1fr)}
}
</style>

<div class="wrap">
  <header>
    <h1>小肥鱼上下文曲线</h1>
    <p class="sub">每轮真正送进模型的上下文有多大、被什么吃掉的、压缩把水位压到哪儿。数据取自 magpie 路由日志，按请求逐条记录。</p>
    <div class="meta" id="meta"></div>
  </header>

  <div class="tiles" id="tiles"></div>

  <section>
    <h2>每次请求的上下文</h2>
    <p class="hint">一条线是一间会话；竖虚线是压缩参数生效的时刻（11-04 21:39）。圆点是压缩回收。</p>
    <div class="controls" role="group" aria-label="时间范围">
      <button class="range" data-h="168" aria-pressed="true">7 天</button>
      <button class="range" data-h="24" aria-pressed="false">24 小时</button>
      <button class="range" data-h="6" aria-pressed="false">6 小时</button>
    </div>
    <div class="chart" id="chart1">
      <div class="tip" id="tip1"></div>
    </div>
    <div class="legend" id="legend1"></div>
  </section>

  <section>
    <h2>这一轮都由什么组成</h2>
    <p class="hint">每间会话最近一次请求的构成。系统提示 + 工具定义是固定开销，对话历史才是会滚大的那部分。</p>
    <div class="bars" id="bars"></div>
    <div class="bar-legend" id="barlegend"></div>
  </section>

  <section>
    <h2>分会话</h2>
    <div class="tw">
      <table>
        <thead><tr><th>会话</th><th>请求</th><th>中位</th><th>p90</th><th>最高</th><th>压缩</th><th>窗口</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </section>

  <footer id="foot"></footer>
</div>

<script>
const D = __DATA__;
const NS = 'http://www.w3.org/2000/svg';
const COLORS = ['--s1','--s2','--s3','--s4'];
const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const k = (v) => (v >= 1000 ? (v/1000).toFixed(v >= 100000 ? 0 : 1) + 'k' : String(v));
const esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmtTime = (ms) => {
  const d = new Date(ms), p = (n) => String(n).padStart(2,'0');
  return `${d.getMonth()+1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const whoList = [...new Set(D.points.map(p => p.who))];
const colorOf = (who) => COLORS[whoList.indexOf(who) % COLORS.length];

// ---------- 概要 ----------
const all = D.points;
const medAll = all.length ? all.map(p=>p.tok).sort((a,b)=>a-b)[Math.floor(all.length/2)] : 0;
const maxAll = all.length ? Math.max(...all.map(p=>p.tok)) : 0;
const compactions = D.stats.reduce((a,s)=>a+s.compactions, 0);
const before = all.filter(p => p.t < D.changeAt).map(p=>p.tok);
const after  = all.filter(p => p.t >= D.changeAt).map(p=>p.tok);
const med = (xs) => xs.length ? xs.slice().sort((a,b)=>a-b)[Math.floor(xs.length/2)] : null;
const medB = med(before), medA = med(after);

document.getElementById('tiles').innerHTML = [
  ['中位上下文', k(medAll), `${all.length} 次主回合请求`],
  ['最高一次', k(maxAll), `窗口上限见下表`],
  ['压缩回收', String(compactions), '近 ' + D.days + ' 天，曲线上的圆点'],
  ['参数生效后', medA === null ? '—' : k(medA),
   medB === null ? '之前没有可比数据' : `之前中位 ${k(medB)}`],
].map(([kk,vv,uu]) => `<div class="tile"><span class="k">${kk}</span><span class="v">${vv}</span><span class="u">${uu}</span></div>`).join('');

document.getElementById('meta').textContent =
  `生成于 ${D.generated} · 覆盖 ${D.days} 天 · ${all.length} 个主回合请求（另有 ${D.skipped} 次小于 8k 的辅助调用未计入）` +
  (after.length === 0 ? ' · 压缩参数 21:39 刚生效，之后的新请求还没出现' : '');

// ---------- 折线图 ----------
let hours = 168;

function drawTimeseries(){
  const host = document.getElementById('chart1');
  host.querySelectorAll('svg').forEach(s => s.remove());
  const W = 880, H = 340, M = {t: 16, r: 52, b: 34, l: 54};
  const narrow = host.clientWidth < 560;
  const now = Math.max(...all.map(p=>p.t), Date.now());
  const t0 = now - hours * 3600e3;
  const pts = all.filter(p => p.t >= t0);
  if (!pts.length) { host.insertAdjacentHTML('beforeend', '<p class="hint">这个范围里没有请求。</p>'); return; }

  const yMax = Math.max(...pts.map(p=>p.tok), 1) * 1.08;
  const x = (t) => M.l + (t - t0) / (now - t0) * (W - M.l - M.r);
  const y = (v) => H - M.b - v / yMax * (H - M.t - M.b);

  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', '各会话每次请求的上下文 token 数随时间变化');

  // 网格与 y 轴
  const g = document.createElementNS(NS,'g'); g.setAttribute('class','grid');
  const ga = document.createElementNS(NS,'g'); ga.setAttribute('class','axis');
  for (let i = 0; i <= 4; i++){
    const v = yMax * i / 4, yy = y(v);
    const ln = document.createElementNS(NS,'line');
    ln.setAttribute('x1', M.l); ln.setAttribute('x2', W - M.r);
    ln.setAttribute('y1', yy); ln.setAttribute('y2', yy);
    g.appendChild(ln);
    const tx = document.createElementNS(NS,'text');
    tx.setAttribute('x', M.l - 8); tx.setAttribute('y', yy + 4); tx.setAttribute('text-anchor','end');
    tx.textContent = k(Math.round(v));
    ga.appendChild(tx);
  }
  // x 轴刻度：窄屏少几个，免得挤成一团
  const xTicks = narrow ? 2 : 4;
  for (let i = 0; i <= xTicks; i++){
    const t = t0 + (now - t0) * i / xTicks;
    const tx = document.createElementNS(NS,'text');
    tx.setAttribute('x', x(t)); tx.setAttribute('y', H - M.b + 18);
    tx.setAttribute('text-anchor', i === 0 ? 'start' : (i === xTicks ? 'end' : 'middle'));
    tx.textContent = fmtTime(t);
    ga.appendChild(tx);
  }
  svg.appendChild(g); svg.appendChild(ga);

  // 参数生效线
  if (D.changeAt >= t0){
    const ln = document.createElementNS(NS,'line');
    ln.setAttribute('class','changerule');
    ln.setAttribute('x1', x(D.changeAt)); ln.setAttribute('x2', x(D.changeAt));
    ln.setAttribute('y1', M.t); ln.setAttribute('y2', H - M.b);
    svg.appendChild(ln);
    const lb = document.createElementNS(NS,'text');
    lb.setAttribute('class','changelabel');
    lb.setAttribute('x', x(D.changeAt) + 6); lb.setAttribute('y', M.t + 12);
    lb.textContent = '压缩参数生效';
    svg.appendChild(lb);
  }

  // 每间会话一条线
  whoList.forEach((who, idx) => {
    const xs = pts.filter(p => p.who === who);
    if (!xs.length) return;
    const d = xs.map((p,i) => `${i?'L':'M'}${x(p.t).toFixed(1)},${y(p.tok).toFixed(1)}`).join(' ');
    const path = document.createElementNS(NS,'path');
    path.setAttribute('class','series');
    path.setAttribute('stroke', cssv(colorOf(who)));
    path.setAttribute('d', d);
    path.setAttribute('fill','none');
    svg.appendChild(path);

    // 压缩回收点
    for (let i = 1; i < xs.length; i++){
      const a = xs[i-1], b = xs[i];
      if (b.tok < a.tok * 0.7 && a.tok - b.tok > 10000){
        const c = document.createElementNS(NS,'circle');
        c.setAttribute('cx', x(b.t)); c.setAttribute('cy', y(b.tok));
        c.setAttribute('r', 4.5);
        c.setAttribute('fill', cssv(colorOf(who)));
        c.setAttribute('class','drop');
        svg.appendChild(c);
      }
    }
    // 末端直标
    const lastP = xs[xs.length - 1];
    const lb = document.createElementNS(NS,'text');
    lb.setAttribute('x', Math.min(x(lastP.t) + 8, W - 6));
    lb.setAttribute('y', y(lastP.tok) + 4);
    lb.setAttribute('class','axis');
    lb.setAttribute('text-anchor','start');
    lb.style.fill = cssv(colorOf(who));
    lb.style.fontSize = '11px';
    lb.textContent = who;
    svg.appendChild(lb);
  });

  // 悬停
  const cross = document.createElementNS(NS,'line');
  cross.setAttribute('class','crosshair');
  cross.setAttribute('y1', M.t); cross.setAttribute('y2', H - M.b);
  cross.style.display = 'none';
  svg.appendChild(cross);
  const tip = document.getElementById('tip1');
  const rect = document.createElementNS(NS,'rect');
  rect.setAttribute('x', M.l); rect.setAttribute('y', M.t);
  rect.setAttribute('width', W - M.l - M.r); rect.setAttribute('height', H - M.t - M.b);
  rect.setAttribute('fill','transparent');
  svg.appendChild(rect);

  rect.addEventListener('mousemove', (e) => {
    const box = svg.getBoundingClientRect();
    const px = (e.clientX - box.left) / box.width * W;
    const t = t0 + (px - M.l) / (W - M.l - M.r) * (now - t0);
    cross.setAttribute('x1', px); cross.setAttribute('x2', px);
    cross.style.display = '';
    const rows = whoList.map(who => {
      const xs = pts.filter(p => p.who === who);
      if (!xs.length) return null;
      let best = xs[0];
      for (const p of xs) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
      if (Math.abs(best.t - t) > (now - t0) * 0.02) return null;
      return {who, best};
    }).filter(Boolean);
    if (!rows.length) { tip.style.display = 'none'; return; }
    tip.innerHTML = `<div style="color:var(--ink-3);margin-bottom:4px">${fmtTime(rows[0].best.t)}</div>` +
      rows.map(r => `<div class="row"><span><span class="dot" style="background:${cssv(colorOf(r.who))}"></span>${esc(r.who)}</span><b>${k(r.best.tok)}</b></div>`).join('');
    tip.style.display = 'block';
    const hostBox = host.getBoundingClientRect();
    let left = e.clientX - hostBox.left + 14;
    if (left + 170 > hostBox.width) left = e.clientX - hostBox.left - 184;
    tip.style.left = Math.max(0, left) + 'px';
    tip.style.top = Math.max(0, e.clientY - hostBox.top - 10) + 'px';
  });
  rect.addEventListener('mouseleave', () => { tip.style.display='none'; cross.style.display='none'; });

  host.appendChild(svg);
}

document.getElementById('legend1').innerHTML = whoList.map(w =>
  `<span><i style="background:${cssv(colorOf(w))}"></i>${esc(w)}</span>`).join('');

document.querySelectorAll('button.range').forEach(b => {
  b.addEventListener('click', () => {
    hours = Number(b.dataset.h);
    document.querySelectorAll('button.range').forEach(o => o.setAttribute('aria-pressed', String(o === b)));
    drawTimeseries();
  });
});

// ---------- 构成条 ----------
const KINDS = [
  ['sys',  '系统提示', '--s1'],
  ['tools','工具定义', '--s2'],
  ['chat', '对话历史', '--s3'],
  ['res',  '工具结果', '--s4'],
  ['other','其他',    '--ink-3'],
];
const bars = whoList.map(who => {
  const p = D.latest[who];
  return {who, p};
}).filter(x => x.p);
document.getElementById('bars').innerHTML = bars.map(({who,p}) => {
  const total = p.tok || 1;
  const segs = KINDS.map(([key,label,color]) => {
    const v = p[key] || 0;
    if (v <= 0) return '';
    const pct = v / total * 100;
    const show = pct >= 9;
    return `<div style="flex:${v} 0 0;background:${cssv(color)}" title="${label} ${k(v)} (${pct.toFixed(0)}%)">${show ? Math.round(pct) + '%' : ''}</div>`;
  }).join('');
  return `<div class="bar-row"><span class="bar-name">${esc(who)}</span><div class="bar">${segs}</div></div>`;
}).join('');
document.getElementById('barlegend').innerHTML = KINDS.map(([_,label,color]) =>
  `<span><i style="background:${cssv(color)}"></i>${label}</span>`).join('');

// ---------- 表 ----------
document.getElementById('rows').innerHTML = D.stats.map(s => `<tr>
  <td>${esc(s.who)}</td><td>${s.n}</td><td>${k(s.median)}</td><td>${k(s.p90)}</td>
  <td>${k(s.max)}</td><td>${s.compactions}</td><td>${k(s.win)}</td></tr>`).join('');

document.getElementById('foot').innerHTML =
  `口径：每次请求的 prompt tokens（含缓存命中的部分）。小于 8k 的调用是记忆抽取一类的辅助请求，不计入。` +
  `压缩回收 = 同一会话相邻两次请求下降 30% 以上且减少超过 1 万。<br>` +
  `数据：<code>~/.config/magpie/routing/*.jsonl(.gz)</code> · 重新生成：<code>python3 tools/ctx_report.py</code>`;

drawTimeseries();
</script>
'''


def main():
    ap = argparse.ArgumentParser(description='QQ 会话上下文曲线')
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()

    点, 跳过, 表 = 收数据(a.days)
    if not 点:
        print('没有数据：确认 magpie 的路由日志和桥配置都在', file=sys.stderr)
        return 1
    统 = 统计(点, 表)
    页 = 画页(点, 统, 跳过, a.days)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(页)
    print('写好 %s（%d 个点，%d 次辅助调用已跳过）' % (a.out, len(点), 跳过))
    for s in 统:
        print('  %-4s n=%-4d 中位 %-7d p90 %-7d 最高 %-7d 压缩 %d' % (
            s['who'], s['n'], s['median'], s['p90'], s['max'], s['compactions']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
