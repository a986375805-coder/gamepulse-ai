# -*- coding: utf-8 -*-
"""
测试表 + 待审核页面生成模块

从原节点ai提取（热度）.py 中提取的 generate_test_schedule() 函数
"""
import os
import json
import sqlite3
import webbrowser
from datetime import datetime
from collections import defaultdict

from merger import normalize_game_name
from database.operations import extract_urls
from scraper.utils import classify_source_by_url

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_MODULE_DIR)
DB_PATH = os.path.join(BASE_DIR, "games_history.db")


def generate_test_schedule():
    """生成测试表 + 待审核页面（白名单匹配）"""

    whitelist_path = os.path.join(BASE_DIR, "game_whitelist.txt")
    whitelist_names = []
    if os.path.exists(whitelist_path):
        with open(whitelist_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split("|")
                name = normalize_game_name(parts[0].strip())
                if name:
                    whitelist_names.append(name)
    def in_whitelist(name):
        return any(name in w or w in name for w in whitelist_names)
    print(f"白名单加载: {len(whitelist_names)} 个游戏")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
               e.need_code, e.is_wiped, e.rating, e.download_count,
               e.tip_links, e.log_text, e.source, e.link,
               e.status, e.source_type, e.manual_reviewed, e.merged_source, rv.verdict as review_verdict, rv.confidence as review_confidence,
        rv.reasoning as review_reasoning, rv.review_date as review_date
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        ORDER BY e.test_time ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    test_events = []
    review_events = []

    for r in rows:
        clean_name = r["clean_name"]
        status = r["status"] or "新增"
        matched = in_whitelist(clean_name)

        if status == "正常":
            test_events.append(r)
        elif status in ("新增", "待审") and matched:
            test_events.append(r)
        elif status in ("新增", "待审") and not matched:
            review_events.append(r)

    print(f"测试表: {len(test_events)} 条 | 待审核: {len(review_events)} 条")

    STATUS_COLORS = {"正常": "#2e7d32", "新增": "#1565c0", "待审": "#e65100", "弃用": "#c62828"}
    STATUS_BG = {"正常": "#e8f5e9", "新增": "#e3f2fd", "待审": "#fff3e0", "弃用": "#fce4ec"}
    TYPE_COLORS = {"公测": "#2e7d32", "内测": "#c62828", "封测": "#f9a825", "新版本": "#1565c0", "日常更新": "#546e7a", "资料片": "#7b1fa2"}

    def esc(s):
        if not s: return ""
        return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

    def build_card_html(e, with_selects=False):
        link_url = e["link"] or ""
        links_str = extract_urls(e["tip_links"]) if e["tip_links"] else ""
        s = f'''
    <div class="card" style="border-left:4px solid {TYPE_COLORS.get(e["test_type"] or "","#ccc")}">
          <div class="card-header">
            <span class="game-name">{esc(e["display_name"] or e["clean_name"])}</span>
            <span style="display:flex;gap:4px;align-items:center;flex-shrink:0">
              <span class="status-badge" style="background:{STATUS_BG.get(e["status"] or "","#eee")};color:{STATUS_COLORS.get(e["status"] or "","#999")}">{esc(e["status"] or "")}</span>
              <span style="font-size:11px;color:#999">{esc(e["source"])}</span>
            </span>
          </div>
          <div class="badges">
            <span class="badge type-{esc(e["test_type"])}">{esc(e["test_type"])}</span>
            <span class="badge">{esc(e["test_name"])}</span>
            {f'<span class="badge need-code">需激活码</span>' if e["need_code"]=="是" else ''}
            {f'<span class="badge wiped">删档</span>' if e["is_wiped"]=="是" else ''}
            {f'<span class="badge" style="background:#e3f2fd;color:#1565c0;font-size:10px">'+esc(e["merged_source"])+'</span>' if e["merged_source"] else ''}
            {f'<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px;border:1px solid #ffcc02">人工已审核</span>' if e["manual_reviewed"] else ''}
          </div>
          <div class="meta">{esc(e["rating"])} 评价 / {esc(e["download_count"])} 下载</div>
          <div class="meta date">{esc(e["test_time"])}</div>
          {f'<div class="log">{esc(e["log_text"])}</div>' if e["log_text"] else ''}
          {f'<a class="link" href="{esc(link_url)}" target="_blank">{esc(classify_source_by_url(link_url) or e["source"] or "来源")}</a>' if link_url else ''}
          {''.join(f'<a class="link" href="{esc(u)}" target="_blank">信源{i+1}</a>' for i,u in enumerate(links_str.split()) if u) if links_str else ''}
        </div>'''
        return s

    # ── 测试表页面 ──
    test_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>游戏测试表</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#f5f5f7; color:#333; }
.header { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:12px 20px; text-align:center; position:sticky; top:0; z-index:10; }
.header h1 { font-size:20px; font-weight:600; }
.header .sub { font-size:12px; opacity:0.8; margin-top:4px; }
.filter-bar { display:flex; gap:8px; padding:10px 16px; background:#fff; border-bottom:1px solid #eee; position:sticky; top:52px; z-index:9; }
.filter-bar input { font-size:15px; padding:8px 14px; border:1px solid #ddd; border-radius:10px; outline:none; background:#fafafa; flex:1; min-width:120px; }
.container { max-width:900px; margin:0 auto; padding:16px; }
.month-group { margin-bottom:24px; }
.month-title { font-size:18px; font-weight:600; color:#667eea; padding:8px 0 12px; border-bottom:2px solid #667eea; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
.month-title .count { font-size:13px; color:#999; font-weight:400; }
.day-group { margin-bottom:8px; }
.day-title { font-size:14px; font-weight:600; color:#555; padding:4px 0 6px; }
.card { background:#fff; border-radius:12px; padding:12px 14px; margin-bottom:8px; box-shadow:0 1px 4px rgba(0,0,0,0.08); overflow:hidden; }
.card-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:4px; }
.game-name { font-size:15px; font-weight:600; color:#333; }
.badges { display:flex; gap:4px; flex-wrap:wrap; margin:4px 0; }
.badge { font-size:11px; padding:1px 8px; border-radius:8px; background:#eef; color:#556; }
.badge.type-公测 { background:#e8f5e9; color:#2e7d32; }
    .badge.type-内测 { background:#ffebee; color:#c62828; }
.badge.type-新版本 { background:#e3f2fd; color:#1565c0; }
.badge.type-资料片 { background:#f3e5f5; color:#7b1fa2; }
.badge.type-日常更新 { background:#eceff1; color:#546e7a; }
.badge.type-首发 { background:#e8f5e9; color:#2e7d32; }
    .badge.type-封测 { background:#fff8e1; color:#f9a825; }
.badge.need-code { background:#ffebee; color:#c62828; }
.badge.wiped { background:#fce4ec; color:#880e4f; }
.meta { font-size:12px; color:#999; margin:2px 0; }
.meta.date { font-size:11px; color:#667eea; font-weight:600; }
.log { font-size:12px; color:#444; background:#f8f8f8; padding:6px 10px; border-radius:6px; margin:4px 0; line-height:1.4; }
.link { font-size:11px; color:#667eea; word-break:break-all; margin:2px 0; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.status-badge { font-size:10px; padding:1px 7px; border-radius:8px; font-weight:600; }
.empty { text-align:center; padding:40px; color:#ccc; font-size:14px; }
.stats { font-size:12px; color:#999; padding:8px 16px; background:#fff; border-bottom:1px solid #eee; text-align:center; }
.rv-badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;margin-left:6px;cursor:pointer}}
.rv-confirmed{{background:#e8f5e9;color:#27ae60;border:1px solid #a5d6a7}}
.rv-contradicted{{background:#fdecea;color:#e74c3c;border:1px solid #f5b7b1}}
.rv-unverified{{background:#fef5e7;color:#f39c12;border:1px solid #fad7a0}}
.crd-bad{{border-left:4px solid #e74c3c!important}}
</style>
</head>
<body>
<div class="header">
  <h1>游戏测试表</h1>
  <div class="sub">状态「正常」+ 白名单匹配游戏 · 共 """ + str(len(test_events)) + """ 条 · <a href="review_candidates.html" style="color:#fff;text-decoration:underline">待审核 (""" + str(len(review_events)) + """)</a></div>
</div>
<div class="stats">数据来源: 好游快爆 / TapTap / 公众号</div>
<div class="filter-bar">
  <input type="text" id="searchInput" placeholder="搜索游戏..." oninput="filterCards(this.value)">
</div>
<div class="container" id="container">"""

    # Group test events by month then day
    grouped = defaultdict(lambda: defaultdict(list))
    for e in test_events:
        t = e["test_time"] or ""
        month_key = t[:7] if len(t) >= 7 else "未知"
        day_key = t[:10] if len(t) >= 10 else "未知"
        grouped[month_key][day_key].append(e)

    for month_key in sorted(grouped.keys(), reverse=True):
        days = grouped[month_key]
        month_total = sum(len(v) for v in days.values())
        test_html += f'<div class="month-group"><div class="month-title">{esc(month_key)} <span class="count">({month_total} 条)</span></div>'
        for day_key in sorted(days.keys(), reverse=True):
            test_html += f'<div class="day-group"><div class="day-title">{esc(day_key)}</div>'
            for e in days[day_key]:
                test_html += build_card_html(e)
            test_html += '</div>'
        test_html += '</div>'

    test_html += """
</div>
<script>
function filterCards(val) {
  document.querySelectorAll('.card').forEach(c => {
    const name = c.querySelector('.game-name').textContent.toLowerCase();
    c.style.display = (!val || name.includes(val.toLowerCase())) ? '' : 'none';
  });
}
</script>
</body>
</html>"""

    test_path = os.path.join(BASE_DIR, "test_schedule.html")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(test_html)
    print(f"测试表已生成: {os.path.abspath(test_path)}")

    # ── 待审核页面 ──
    review_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>待审核 - 落选游戏</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#f5f5f7; color:#333; overflow:hidden; height:100vh; }
.header { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:10px 20px; text-align:center; position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:center; gap:12px; }
.header h1 { font-size:18px; font-weight:600; }
.header .sub { font-size:11px; opacity:0.8; }
.save-area { position:absolute; right:16px; }
.save-btn { font-size:12px; padding:4px 12px; border-radius:8px; background:#667eea; color:#fff; cursor:pointer; user-select:none; font-weight:600; border:1px solid rgba(255,255,255,0.3); }
.save-btn:hover { background:#7b93ff; }
.container { height:calc(100vh - 90px); overflow-x:auto; overflow-y:hidden; white-space:nowrap; padding:12px 16px; }
.day-col { display:inline-block; vertical-align:top; width:360px; height:100%; overflow-y:auto; margin-right:12px; white-space:normal; }
.day-col:last-child { margin-right:0; }
.day-col::-webkit-scrollbar { width:4px; }
.day-col::-webkit-scrollbar-thumb { background:#ddd; border-radius:2px; }
.day-header { font-size:15px; font-weight:600; color:#667eea; padding:6px 0 10px; border-bottom:2px solid #667eea; margin-bottom:8px; position:sticky; top:0; background:#f5f5f7; z-index:1; display:flex; align-items:center; gap:8px; }
.day-header .count { font-size:12px; color:#999; font-weight:400; margin-left:auto; }
.card { background:#fff; border-radius:10px; padding:10px 12px; margin-bottom:8px; box-shadow:0 1px 3px rgba(0,0,0,0.08); }
.card { overflow:hidden; }

.card-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:3px; }
.game-name { font-size:14px; font-weight:600; color:#333; cursor:pointer; }
.game-name:hover { color:#667eea; }
.badges { display:flex; gap:3px; flex-wrap:wrap; margin:3px 0; }
.badge { font-size:10px; padding:1px 7px; border-radius:6px; background:#eef; color:#556; }
.badge.type-公测 { background:#e8f5e9; color:#2e7d32; }
    .badge.type-内测 { background:#ffebee; color:#c62828; }
.badge.type-新版本 { background:#e3f2fd; color:#1565c0; }
.badge.type-资料片 { background:#f3e5f5; color:#7b1fa2; }
.badge.type-日常更新 { background:#eceff1; color:#546e7a; }
    .badge.type-封测 { background:#fff8e1; color:#f9a825; }
.badge.need-code { background:#ffebee; color:#c62828; }
.badge.wiped { background:#fce4ec; color:#880e4f; }
.meta { font-size:11px; color:#999; margin:2px 0; }
.log { font-size:12px; color:#444; background:#f8f8f8; padding:4px 8px; border-radius:4px; margin:3px 0; line-height:1.3; max-height:2.6em; overflow:hidden; }
.link { font-size:10px; color:#667eea; word-break:break-all; margin:1px 0; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.empty { text-align:center; padding:30px; color:#ccc; font-size:13px; white-space:normal; }
.status-badge { font-size:10px; padding:1px 6px; border-radius:6px; font-weight:600; }
.move-btn { font-size:11px; padding:3px 10px; border:none; border-radius:6px; cursor:pointer; user-select:none; }
.move-to-schedule { background:#e8f5e9; color:#2e7d32; border:1px solid #c8e6c9; }
.move-to-schedule:hover { background:#c8e6c9; }
.rv-badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;margin-left:6px;cursor:pointer}}
.rv-confirmed{{background:#e8f5e9;color:#27ae60;border:1px solid #a5d6a7}}
.rv-contradicted{{background:#fdecea;color:#e74c3c;border:1px solid #f5b7b1}}
.rv-unverified{{background:#fef5e7;color:#f39c12;border:1px solid #fad7a0}}
.crd-bad{{border-left:4px solid #e74c3c!important}}
</style>
</head>
<body>
<div class="header">
  <h1>待审核 - 落选游戏</h1>
  <div class="sub">新增/待审 · 未匹配白名单 · 共 """ + str(len(review_events)) + """ 条 · <a href="test_schedule.html" style="color:#fff;text-decoration:underline">测试表 (""" + str(len(test_events)) + """)</a></div>
  <div class="save-area">
    <span class="save-btn" id="saveBtn" onclick="saveAll()">保存</span>
  </div>
</div>
<div class="container" id="container">"""

    # Group review events by date
    review_grouped = defaultdict(list)
    for e in review_events:
        day_key = (e["test_time"] or "")[:10]
        review_grouped[day_key].append(e)

    for day_key in sorted(review_grouped.keys()):
        review_html += f'<div class="day-col">'
        review_html += f'<div class="day-header">{esc(day_key)} <span class="count">{len(review_grouped[day_key])} 条</span></div>'
        for e in review_grouped[day_key]:
            link_url = e["link"] or ""
            links_str = extract_urls(e["tip_links"]) if e["tip_links"] else ""
            eid = e["id"]
            ename = esc(e["display_name"] or e["clean_name"])
            etype = esc(e["test_type"])
            estatus = esc(e["status"] or "新增")
            review_html += f'''
            <div class="card" style="border-left:4px solid {TYPE_COLORS.get(e["test_type"] or "","#ccc")}">
              <div class="card-header">
                <span class="game-name">{ename}</span>
                <span style="display:flex;gap:4px;align-items:center;flex-shrink:0">
                  <span class="status-badge" style="background:{STATUS_BG.get(e["status"] or "","#eee")};color:{STATUS_COLORS.get(e["status"] or "","#999")}">{estatus}</span>
                  <span style="font-size:10px;color:#999">{esc(e["source"])}</span>
                </span>
              </div>
              <div class="badges">
                <span class="badge type-{esc(e["test_type"])}">{esc(e["test_type"])}</span>
                <span class="badge">{esc(e["test_name"])}</span>
                {f'<span class="badge need-code">需激活码</span>' if e["need_code"]=="是" else ''}
                {f'<span class="badge wiped">删档</span>' if e["is_wiped"]=="是" else ''}
              {f'<span class="badge" style="background:#e3f2fd;color:#1565c0;font-size:10px">'+esc(e["merged_source"])+'</span>' if e.get("merged_source") else ''}
              {f'<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px;border:1px solid #ffcc02">\\u4eba\\u5de5\\u5df2\\u5ba1\\u6838</span>' if e.get("manual_reviewed") else ''}
              </div>
              <div class="meta">{esc(e["rating"])} 评价 / {esc(e["download_count"])} 下载</div>
              {f'<div class="log">{esc(e["log_text"])}</div>' if e["log_text"] else ''}
              {f'<a class="link" href="{esc(link_url)}" target="_blank">{esc(classify_source_by_url(link_url) or e["source"] or "来源")}</a>' if link_url else ''}
              {''.join(f'<a class="link" href="{esc(u)}" target="_blank">信源{i+1}</a>' for i,u in enumerate(links_str.split()) if u) if links_str else ''}
              <div style="margin-top:4px;display:flex;gap:4px;align-items:center;flex-wrap:wrap">
                <span style="font-size:10px;color:#999">状态:</span>
                <select style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:4px" onchange="trackChange({eid},'status',this.value)">
                  <option value="正常" {"selected" if e["status"]=="正常" else ""}>正常</option>
                  <option value="新增" {"selected" if e["status"]=="新增" else ""}>新增</option>
                  <option value="待审" {"selected" if e["status"]=="待审" else ""}>待审</option>
                  <option value="弃用" {"selected" if e["status"]=="弃用" else ""}>弃用</option>
                </select>
                <span style="font-size:10px;color:#999;margin-left:4px">类型:</span>
                <select style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:4px" onchange="trackChange({eid},'type',this.value)">
                  <option value="公测" {"selected" if e["test_type"]=="公测" else ""}>公测</option>
                  <option value="内测" {"selected" if e["test_type"]=="内测" else ""}>内测</option>
                  <option value="封测" {"selected" if e["test_type"]=="封测" else ""}>封测</option>
                  <option value="新版本" {"selected" if e["test_type"]=="新版本" else ""}>新版本</option>
                  <option value="资料片" {"selected" if e["test_type"]=="资料片" else ""}>资料片</option>
                  <option value="日常更新" {"selected" if e["test_type"]=="日常更新" else ""}>日常更新</option>
                </select>
              </div>
              <div style="margin-top:6px;display:flex;gap:6px;align-items:center">
                <span class="move-btn move-to-schedule" onclick="moveToSchedule({eid},'{esc(e["clean_name"])}')">移入测试表</span>
              </div>
            </div>'''
        review_html += '</div>'

    review_html += f"""
</div>
<script>
const API_URL = {json.dumps("http://127.0.0.1:8765")};
const API_BASE = API_URL;
const PENDING = {{}};
let WHITELIST = [];
fetch(API_BASE + '/api/whitelist').then(r => r.json()).then(w => {{ WHITELIST = w.map(x => ({{name:x.name, id:x.id||''}})); }}).catch(() => {{}});
function trackChange(eventId, field, value) {{
  if (!PENDING[eventId]) PENDING[eventId] = {{}};
  PENDING[eventId][field] = value;
  updateSaveBtn();
}}
function updateSaveBtn() {{
  const n = Object.keys(PENDING).length;
  const btn = document.getElementById('saveBtn');
  if (!btn) return;
  btn.textContent = n ? '保存 ('+n+')' : '保存';
}}
async function fetchRetry(url, options, maxRetries=3) {{
  for (let i=0; i<=maxRetries; i++) {{
    try {{
      let resp = await fetch(url, options);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return await resp.json();
    }} catch(e) {{
      if (i === maxRetries) throw e;
      await new Promise(r => setTimeout(r, 500 * (i+1)));
    }}
  }}
}}
async function moveToSchedule(id, clean) {{
  try {{
    let allGames = WHITELIST.map(w => ({{name:w.name, id:w.id||''}}));
    if (!allGames.some(g => g.name === clean)) {{
      allGames.push({{name:clean, id:''}});
    }}
    let resp = await fetch(API_BASE + '/api/whitelist', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{games:allGames}})
    }});
    let result = await resp.json();
    if (result.ok) {{
      WHITELIST.length = 0;
      allGames.forEach(g => WHITELIST.push({{name:g.name, id:g.id}}));
    }}
  }} catch(e) {{ console.error('whitelist add fail', e); }}
  trackChange(id, 'exported', 0);
  trackChange(id, 'removed', 0);
  saveAll();
}}
async function saveAll() {{
  const items = Object.entries(PENDING).map(([id, changes]) => ({{id:+id, ...changes}}));
  if (!items.length) return;
  if (!API_URL) {{ alert('请先启动 API 服务'); return; }}
  try {{
    let result = await fetchRetry(API_BASE + '/api/batch_update', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify(items)
    }});
    if (result.ok) {{
      Object.keys(PENDING).forEach(id => {{ PENDING[id] = null; delete PENDING[id]; }});
      updateSaveBtn();
      alert('保存成功');
    }} else {{
      alert('保存失败: ' + (result.error || '未知错误'));
    }}
  }} catch(e) {{ alert('保存失败: ' + e.message); }}
}}
</script>
</body>
</html>"""

    review_path = os.path.join(BASE_DIR, "review_candidates.html")
    with open(review_path, "w", encoding="utf-8") as f:
        f.write(review_html)
    print(f"待审核页面已生成: {os.path.abspath(review_path)}")

    webbrowser.open(os.path.abspath(test_path))
    webbrowser.open(os.path.abspath(review_path))
