import os
import json
import re
import webbrowser
import sqlite3
from datetime import datetime
import csv
import pandas as pd

from database.operations import extract_urls
from scraper.utils import classify_source_by_url
from merger import normalize_game_name


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_MODULE_DIR)
DB_PATH = os.path.join(BASE_DIR, "games_history.db")


def generate_kanban(api_url=None):
    """生成四栏看板 HTML"""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
               e.need_code, e.is_wiped, e.rating, e.download_count,
               e.tip_links, e.log_text, e.source, e.link,
               e.status, e.source_type, e.scrape_date,
               e.manual_reviewed, e.merged_source, rv.verdict as review_verdict, rv.confidence as review_confidence,
        rv.reasoning as review_reasoning, rv.review_date as review_date
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        ORDER BY e.test_time DESC
    """)
    rows = cur.fetchall()
    conn.close()

    events = []
    for r in rows:
        link_url = r["link"] or ""
        status = r["status"] or "新增"
        if status not in ("正常", "新增", "待审", "弃用"):
            status = "新增"
        events.append({
            "id": r["id"],
            "game": r["display_name"] or r["clean_name"],
            "clean": r["clean_name"],
            "test_name": r["test_name"],
            "date": r["test_time"],
            "test_type": r["test_type"],
            "need_code": r["need_code"],
            "is_wiped": r["is_wiped"],
            "rating": r["rating"] or "",
            "download": r["download_count"] or "",
            "links": extract_urls(r["tip_links"]),
            "log": r["log_text"] or "",
            "source": r["source"] or "",
            "url": link_url,
            "review_verdict":r["review_verdict"] or "","review_confidence":r["review_confidence"] or "","review_reasoning":r["review_reasoning"] or "","review_date":r["review_date"] or "","link_label": classify_source_by_url(link_url) or r["source"] or "原链接",
            "status": r["status"] or "新增",
            "source_type": r["source_type"] or "scrape",
            "scrape_date": r["scrape_date"] or "",
            "manual_reviewed": r["manual_reviewed"] or 0,
            "merged_source": r["merged_source"] or "",
        })

    api_js = ""
    if api_url:
        api_js = f"""
const API_URL = {json.dumps(api_url)};
const API_BASE = (window.location.protocol === 'file:') ? API_URL : window.location.origin;
async function updateStatus(eventId, newStatus) {{
  try {{
    let resp = await fetch(API_BASE + '/api/update_status', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{id:eventId, status:newStatus}})
    }});
    let result = await resp.json();
    if (result.ok) {{
      let ev = allEvents.find(e => e.id === eventId);
      if (ev) ev.status = newStatus;
      applyFilter();
    }} else {{
      alert('更新失败: ' + (result.error || ''));
    }}
  }} catch(e) {{
    alert('网络错误: ' + e.message);
  }}
}}
"""

    STATUS_LABELS = {"正常": "正常", "新增": "新增", "待审": "待审", "弃用": "弃用"}
    STATUS_COLORS = {"正常": "#e8f5e9", "新增": "#e3f2fd", "待审": "#fff3e0", "弃用": "#fce4ec"}
    STATUS_HEADER_COLORS = {"正常": "#2e7d32", "新增": "#1565c0", "待审": "#e65100", "弃用": "#c62828"}

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>游戏节点看板</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#f0f2f5; color:#333; height:100vh; display:flex; flex-direction:column; }}
.header {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:12px 16px 10px; text-align:center; flex-shrink:0; }}
.header h1 {{ font-size:17px; font-weight:600; }}
.header .sub {{ font-size:12px; opacity:0.8; margin-top:2px; }}
.filter-bar {{ display:flex; gap:6px; padding:8px 12px; background:#fff; border-bottom:1px solid #eee; overflow-x:auto; flex-shrink:0; }}
.filter-bar input,.filter-bar select {{ font-size:13px; padding:5px 10px; border:1px solid #ddd; border-radius:8px; outline:none; background:#fafafa; flex-shrink:0; }}
.filter-bar input {{ flex:1; min-width:100px; }}
.filter-bar select {{ min-width:70px; }}
.kanban {{ flex:1; display:flex; gap:10px; padding:10px 12px; overflow-x:auto; overflow-y:hidden; }}
.kanban-col {{ flex:1; min-width:280px; max-width:400px; display:flex; flex-direction:column; background:#f8f9fb; border-radius:12px; overflow:hidden; }}
.col-header {{ padding:10px 12px; font-size:14px; font-weight:600; display:flex; justify-content:space-between; align-items:center; }}
.col-header .count {{ font-size:12px; background:rgba(0,0,0,0.08); padding:1px 8px; border-radius:10px; }}
.col-body {{ flex:1; overflow-y:auto; padding:6px 8px; }}
.card {{ background:#fff; border-radius:8px; padding:8px 10px; margin-bottom:6px; box-shadow:0 1px 2px rgba(0,0,0,0.05); }}
.card-header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:3px; }}
.game-name {{ font-size:13px; font-weight:600; color:#333; cursor:pointer; }}
.game-name:hover {{ color:#667eea; }}
.badges {{ display:flex; gap:3px; flex-wrap:wrap; margin:3px 0; }}
.badge {{ font-size:9px; padding:1px 6px; border-radius:6px; background:#eef; color:#556; }}
.badge.type-公测 {{ background:#e8f5e9; color:#2e7d32; }}
    .badge.type-内测 {{ background:#ffebee; color:#c62828; }}
.badge.type-新版本 {{ background:#e3f2fd; color:#1565c0; }}
.badge.type-资料片 {{ background:#f3e5f5; color:#7b1fa2; }}
.badge.type-日常更新 {{ background:#eceff1; color:#546e7a; }}
.badge.type-首发 {{ background:#e8f5e9; color:#2e7d32; }}
    .badge.type-封测 {{ background:#fff8e1; color:#f9a825; }}
.badge.need-code {{ background:#ffebee; color:#c62828; }}
.badge.wiped {{ background:#fce4ec; color:#880e4f; }}
.meta {{ font-size:10px; color:#999; margin:2px 0; }}
.log {{ font-size:11px; color:#555; background:#fafafa; padding:4px 6px; border-radius:4px; margin:3px 0; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
.link {{ font-size:10px; color:#667eea; word-break:break-all; margin:1px 0; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.source-tag {{ font-size:10px; padding:1px 5px; border-radius:4px; background:#eef; color:#667eea; }}
.action-btn {{ font-size:11px; padding:3px 10px; border:none; border-radius:6px; cursor:pointer; margin-top:4px; }}
.action-btn.discard {{ background:#fce4ec; color:#c62828; }}
.action-btn.discard:hover {{ background:#ffcdd2; }}
.action-btn.restore {{ background:#e8f5e9; color:#2e7d32; }}
.action-btn.restore:hover {{ background:#c8e6c9; }}
.empty {{ text-align:center; padding:20px; color:#ccc; font-size:12px; }}
.modal-overlay {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:100; justify-content:center; align-items:flex-start; padding-top:50px; }}
.modal-overlay.show {{ display:flex; }}
.modal {{ background:#fff; border-radius:16px 16px 0 0; width:100%; max-width:500px; max-height:80vh; overflow-y:auto; padding:18px 20px; margin:0 12px; box-shadow:0 -4px 20px rgba(0,0,0,0.15); }}
.modal h2 {{ font-size:16px; margin-bottom:10px; }}
.modal-item {{ padding:8px 0; border-bottom:1px solid #f0f0f0; }}
.modal-item:last-child {{ border-bottom:none; }}
.modal-item .mi-date {{ font-size:12px; color:#667eea; font-weight:600; }}
.modal-item .mi-info {{ font-size:12px; color:#555; margin:2px 0; }}
.modal-close {{ margin-top:10px; width:100%; padding:10px; border:none; border-radius:8px; background:#f0f0f0; font-size:14px; cursor:pointer; }}
.rv-badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;margin-left:6px;cursor:pointer}}
.rv-confirmed{{background:#e8f5e9;color:#27ae60;border:1px solid #a5d6a7}}
.rv-contradicted{{background:#fdecea;color:#e74c3c;border:1px solid #f5b7b1}}
.rv-unverified{{background:#fef5e7;color:#f39c12;border:1px solid #fad7a0}}
.crd-bad{{border-left:4px solid #e74c3c!important}}
</style>
</head>
<body>
<div class="header">
  <h1>游戏节点看板</h1>
  <div class="sub">正常 · 新增 · 待审 · 弃用</div>
</div>
<div class="filter-bar">
  <input type="text" id="searchInput" placeholder="搜索游戏..." oninput="applyFilter()">
  <select id="typeFilter" onchange="applyFilter()">
    <option value="">全部类型</option>
    <option value="公测">公测</option>
    <option value="内测">内测</option>
    <option value="新版本">新版本</option>
    <option value="资料片">资料片</option>
    <option value="日常更新">日常更新</option>
    <option value="封测">封测</option>
  </select>
  <select id="sourceFilter" onchange="applyFilter()">
    <option value="">全部来源</option>
    <option value="scrape">爬取</option>
    <option value="public_account">公众号</option>
  </select>
</div>
<div class="kanban" id="kanban"></div>
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <h2 id="modalTitle">--</h2>
    <div id="modalBody"></div>
    <button class="modal-close" onclick="closeModal()">关闭</button>
  </div>
</div>
<script>
{api_js}
const DATA = {json.dumps(events, ensure_ascii=False)};
const STATUSES = ['正常','新增','待审','弃用'];
const STATUS_COLORS = {{'正常':'#e8f5e9','新增':'#e3f2fd','待审':'#fff3e0','弃用':'#fce4ec'}};
const STATUS_HDR = {{'正常':'#2e7d32','新增':'#1565c0','待审':'#e65100','弃用':'#c62828'}};

function parseDate(s) {{
  if (!s) return null;
  let m = s.match(/(\\d{{4}})\\/(\\d{{1,2}})\\/(\\d{{1,2}})/);
  if (m) return new Date(+m[1],+m[2]-1,+m[3]);
  m = s.match(/(\\d{{4}})-(\\d{{1,2}})-(\\d{{1,2}})/);
  if (m) return new Date(+m[1],+m[2]-1,+m[3]);
  return null;
}}
function fmtDate(d) {{ return d.getFullYear()+'/'+((d.getMonth()+1)+'').padStart(2,'0')+'/'+(d.getDate()+'').padStart(2,'0'); }}
function esc(s) {{ if(!s)return ''; return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }}

const allEvents = DATA;

function render(filterGame, filterType, filterSource) {{
  const kanban = document.getElementById('kanban');
  kanban.innerHTML = '';

  for (const status of STATUSES) {{
    let col = document.createElement('div');
    col.className = 'kanban-col';

    let items = allEvents.filter(e => e.status === status);
    if (filterGame) {{
      items = items.filter(e => e.game.includes(filterGame) || e.clean.includes(filterGame));
    }}
    if (filterType) {{
      items = items.filter(e => e.test_type === filterType);
    }}
    if (filterSource) {{
      items = items.filter(e => e.source_type === filterSource);
    }}

    items.sort((a,b) => {{
      let da = parseDate(a.date), db = parseDate(b.date);
      if (!da || !db) return 0;
      return db - da;
    }});

    let hdr = document.createElement('div');
    hdr.className = 'col-header';
    hdr.style.background = STATUS_COLORS[status] || '#f8f9fb';
    hdr.innerHTML = `<span style="color:${{STATUS_HDR[status]||'#333'}}">${{status}}</span><span class="count">${{items.length}}</span>`;
    col.appendChild(hdr);

    let body = document.createElement('div');
    body.className = 'col-body';

    if (items.length === 0) {{
      body.innerHTML = '<div class="empty">暂无</div>';
    }} else {{
      for (const e of items) {{
        let card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="card-header">
            <span class="game-name" onclick="event.stopPropagation();showHistory('${{e.clean.replace(/'/g,"\\\\'")}}','${{e.game.replace(/'/g,"\\\\'")}}')">${{esc(e.game)}}</span>
            <span style="font-size:10px;color:#999">{{e.scrape_date?'\U0001f4c5'+esc(e.scrape_date)+' ':''}}{{e.source_type === 'public_account' ? '公众号' : e.source || '爬取'}}</span>
          </div>
          <div class="badges">
            <span class="badge type-${{esc(e.test_type)}}">${{esc(e.test_type)}}</span>
            <span class="badge">${{esc(e.test_name)}}</span>
            ${{e.need_code==='是'?'<span class="badge need-code">需激活码</span>':''}}
            ${{e.is_wiped==='是'?'<span class="badge wiped">删档</span>':''}}
            ${{e.merged_source ? '<span class="badge" style="background:#e3f2fd;color:#1565c0;font-size:9px">'+esc(e.merged_source)+'</span>' : ''}}
            ${{e.manual_reviewed ? '<span class="badge" style="background:#fff3e0;color:#e65100;font-size:9px;border:1px solid #ffcc02">\\u4eba\\u5de5\\u5df2\\u5ba1\\u6838</span>' : ''}}
            <span class="badge" style="background:#f5f5f5">${{esc(e.date)}}</span>
          </div>
          ${{e.log ? `<div class="log">${{esc(e.log)}}</div>` : ''}}
          ${{e.url ? `<a class="link" href="${{esc(e.url)}}" target="_blank" onclick="event.stopPropagation()">${{esc(e.link_label || '来源')}}</a>` : ''}}
          ${{e.links ? e.links.split(' ').filter(Boolean).map((u, i) => `<a class="link" href="${{esc(u)}}" target="_blank" onclick="event.stopPropagation()">信源${{i+1}}</a>`).join('') : ''}}
          ${{status === '待审' && API_URL ? `<button class="action-btn discard" onclick="event.stopPropagation();updateStatus(${{e.id}},'弃用')">标记弃用</button>` : ''}}
          ${{status === '弃用' && API_URL ? `<button class="action-btn restore" onclick="event.stopPropagation();updateStatus(${{e.id}},'待审')">恢复待审</button>` : ''}}
        `;
        body.appendChild(card);
      }}
    }}
    col.appendChild(body);
    kanban.appendChild(col);
  }}
}}

function applyFilter() {{
  render(
    document.getElementById('searchInput').value.trim(),
    document.getElementById('typeFilter').value,
    document.getElementById('sourceFilter').value
  );
}}

function showHistory(cleanName, displayName) {{
  document.getElementById('modalTitle').textContent = displayName + ' - 历史节点';
  let body = document.getElementById('modalBody');
  body.innerHTML = '';
  let filtered = allEvents.filter(e => e.clean === cleanName);
  if (filtered.length === 0) {{
    body.innerHTML = '<div style="text-align:center;padding:20px;color:#999">暂无历史记录</div>';
  }} else {{
    filtered.sort((a,b) => a.date < b.date ? 1 : -1);
    for (const e of filtered) {{
      let div = document.createElement('div');
      div.className = 'modal-item';
      div.innerHTML = `
        <div class="mi-date">${{esc(e.date)}} <span style="float:right;font-size:11px;color:#999">[${{esc(e.status)}}]</span></div>
        <div class="mi-info">${{esc(e.test_name)}} | ${{esc(e.test_type)}} | ${{e.scrape_date?'\U0001f4c5'+esc(e.scrape_date)+' ':''}}${{e.source_type === 'public_account' ? '公众号' : (esc(e.source) || '爬取')}}</div>
      `;
      body.appendChild(div);
    }}
  }}
  document.getElementById('modalOverlay').classList.add('show');
}}
function closeModal() {{ document.getElementById('modalOverlay').classList.remove('show'); }}
document.getElementById('modalOverlay').addEventListener('click', e => {{ if(e.target===e.currentTarget) closeModal(); }});

render('','','');
</script>
</body>
</html>"""

    path = os.path.join(BASE_DIR, "kanban.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"看板已生成: {os.path.abspath(path)}")
    webbrowser.open(os.path.abspath(path))
