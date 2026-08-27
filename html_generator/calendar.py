# -*- coding: utf-8 -*-
"""
Calendar generation module - extracted from 节点ai提取（热度）.py
"""

import sys
import io
import os
import json
import re
import webbrowser
import csv
import sqlite3
from datetime import datetime, timedelta
import pandas as pd

from database.operations import extract_urls
from scraper.utils import classify_source_by_url
from merger import normalize_game_name

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_MODULE_DIR)
DB_PATH = os.path.join(BASE_DIR, "games_history.db")

def generate_calendar(api_url=None):
    """生成日期看板（按日期分组，状态颜色 + 下拉修改）"""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
         SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
                e.need_code, e.is_wiped, e.is_formal, e.exported, e.removed_from_schedule,
                e.rating, e.download_count,
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
        events.append({
            "id": r["id"],
            "game": r["display_name"] or r["clean_name"],
            "clean": r["clean_name"],
            "test_name": r["test_name"],
            "date": r["test_time"],
            "test_type": r["test_type"],
            "need_code": r["need_code"] or "",
            "is_wiped": r["is_wiped"] or "",
            "is_formal": r["is_formal"] or "",
            "exported": r["exported"] or 0,
            "removed": r["removed_from_schedule"] or 0,
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

    whitelist_path = os.path.join(BASE_DIR, "game_whitelist.txt")
    mapping_path = os.path.join(BASE_DIR, "complete_game_mapping.csv")
    game_code_map = {}
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = normalize_game_name(row.get("Name", ""))
                code = row.get("GameCode", "").strip()
                if name and code:
                    game_code_map[name] = code
    whitelist_entries = []
    if os.path.exists(whitelist_path):
        with open(whitelist_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                raw_name = parts[0].strip()
                name = normalize_game_name(raw_name)
                eid = parts[1].strip() if len(parts) > 1 else game_code_map.get(name, "")
                if name:
                    whitelist_entries.append({"name": name, "id": eid})
    whitelist_json = json.dumps(whitelist_entries, ensure_ascii=False)
    events_json = json.dumps(events, ensure_ascii=False)

    api_url_value = json.dumps(api_url)
    pending_save = f"""
const PENDING = {{}};
function trackChange(eventId, field, value) {{
  if (!PENDING[eventId]) PENDING[eventId] = {{}};
  PENDING[eventId][field] = value;
  updateSaveBtn();
  triggerAutoSave();
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
async function saveAll() {{
  const items = Object.entries(PENDING).map(([id, changes]) => ({{id:+id, ...changes}}));
  if (!items.length) return;
  if (!API_URL) {{ alert('请先运行 --serve 启动 API 服务'); return; }}
  try {{
    let result = await fetchRetry(API_BASE + '/api/batch_update', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify(items)
    }});
    if (result.ok) {{
      for (const item of items) {{
        const idx = allEvents.findIndex(e => e.id === item.id);
        if (idx >= 0) {{
          if (item.status) allEvents[idx].status = item.status;
          if (item.type) allEvents[idx].test_type = item.type;
          if (item.test_name) allEvents[idx].test_name = item.test_name;
          if (item.name) {{ allEvents[idx].game = item.name; allEvents[idx].clean = item.name; }}
          if (item.test_time) {{ allEvents[idx].date = item.test_time; }}
          if (item.need_code) {{ allEvents[idx].need_code = item.need_code; }}
          if (item.is_wiped) {{ allEvents[idx].is_wiped = item.is_wiped; }}
          if (item.is_formal) {{ allEvents[idx].is_formal = item.is_formal; }}
          if (item.exported !== undefined) {{ allEvents[idx].exported = item.exported; }}
          if (item.removed !== undefined) {{ allEvents[idx].removed = item.removed; }}
          if (item.manual_reviewed !== undefined) {{ allEvents[idx].manual_reviewed = item.manual_reviewed; localStorage.setItem('mr_'+item.id, item.manual_reviewed); }}
        }}
      }}
      allDates = {{}};
      for (const e of allEvents) {{
        let d = parseDate(e.date);
        if (!d) continue;
        let key = fmtDate(d);
        if (!allDates[key]) allDates[key] = [];
        allDates[key].push(e);
      }}
      sortedKeys = Object.keys(allDates).sort();
      Object.keys(PENDING).forEach(id => {{ PENDING[id] = null; delete PENDING[id]; }});
      updateSaveBtn();
      switchView(currentView);
    }} else {{
      alert('保存失败: ' + (result.error || '未知错误'));
    }}
  }} catch(e) {{
    alert('保存失败: ' + e.message);
  }}
}}

let autoSaveTimer = null;
function triggerAutoSave() {{
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => saveAll(), 1200);
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
async function deleteEvent(id) {{
  if (!confirm('确认永久删除该节点？')) return;
  try {{
    let resp = await fetch(API_BASE + '/api/delete_event', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{id}})
    }});
    let result = await resp.json();
    if (result.ok) {{
      allEvents = allEvents.filter(e => e.id !== id);
      allDates = {{}};
      for (const e of allEvents) {{
        let d = parseDate(e.date);
        if (!d) continue;
        let key = fmtDate(d);
        if (!allDates[key]) allDates[key] = [];
        allDates[key].push(e);
      }}
      sortedKeys = Object.keys(allDates).sort();
      closeModal();
      const search = document.getElementById('searchInput').value.trim();
      if (currentView === 'calendar') render(search);
      else if (currentView === 'schedule') renderTestSchedule(search);
      else if (currentView === 'review') renderReview(search);
    }} else {{
      alert('删除失败: ' + (result.error || '未知错误'));
    }}
  }} catch(e) {{ alert('删除失败: ' + e.message); }}
}}
"""

    html = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>游戏节点日历</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#f5f5f7; color:#333; overflow:hidden; height:100vh; }
.header { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:10px 20px; text-align:center; position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:center; gap:12px; }
.header h1 { font-size:20px; font-weight:600; }
.save-area { position:absolute; right:16px; }
.save-btn { display:inline-block; font-size:13px; padding:5px 14px; border-radius:8px; background:#667eea; color:#fff; cursor:pointer; user-select:none; font-weight:600; border:1px solid rgba(255,255,255,0.3); }
.save-btn:hover { background:#7b93ff; }
.filter-bar { display:flex; gap:8px; padding:10px 16px; background:#fff; border-bottom:1px solid #eee; align-items:center; }
.filter-bar input { font-size:15px; padding:8px 14px; border:1px solid #ddd; border-radius:10px; outline:none; background:#fafafa; flex:1; min-width:120px; }
.col-filter-inline { display:none; margin:4px 0 6px; padding:6px 8px; background:#f0f0f5; border-radius:8px; font-size:12px; }
.col-filter-inline.show { display:block; }
.col-filter-inline .cfi-row { display:flex; align-items:center; gap:4px; margin:2px 0; flex-wrap:wrap; }
.col-filter-inline .cfi-label { color:#888; font-size:11px; flex-shrink:0; min-width:28px; }
.col-filter-inline .cfi-chip { display:inline-block; padding:1px 8px; border-radius:6px; border:1px solid #ddd; background:#fff; color:#555; cursor:pointer; user-select:none; font-size:11px; line-height:1.6; }
.col-filter-inline .cfi-chip:hover { border-color:#667eea; }
.col-filter-inline .cfi-chip.active { background:#667eea; color:#fff; border-color:#667eea; }
.col-filter-inline .cfi-close { cursor:pointer; color:#999; font-size:12px; margin-left:auto; padding:0 4px; }
.col-filter-inline .cfi-close:hover { color:#333; }
.cf-toggle { font-size:13px; cursor:pointer; color:#999; padding:0 4px; user-select:none; }
.cf-toggle:hover { color:#667eea; }
.cf-toggle.active { color:#667eea; }
.container { height:calc(100vh - 130px); overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch; white-space:nowrap; padding:16px 20px; scroll-behavior:smooth; }
.day-col { display:inline-block; vertical-align:top; width:380px; height:calc(100vh - 165px); overflow-y:auto; margin-right:16px; white-space:normal; }
.day-col:last-child { margin-right:0; }
.day-col::-webkit-scrollbar { width:4px; }
.day-col::-webkit-scrollbar-thumb { background:#ddd; border-radius:2px; }
.day-header { font-size:16px; font-weight:600; color:#667eea; padding:8px 0 12px; border-bottom:2px solid #667eea; margin-bottom:10px; position:sticky; top:0; background:#f5f5f7; z-index:1; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.day-header .weekday { font-size:13px; color:#999; font-weight:400; }
.day-header .count { font-size:13px; color:#999; font-weight:400; margin-left:auto; }

.card { background:#fff; border-radius:12px; padding:14px 16px; margin-bottom:10px; box-shadow:0 1px 4px rgba(0,0,0,0.08); cursor:pointer; transition:box-shadow 0.2s; }
.card:active { box-shadow:0 2px 8px rgba(0,0,0,0.12); }
.card-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; }
.game-name { font-size:16px; font-weight:600; color:#333; cursor:pointer; }
.game-name:hover { color:#667eea; }
.badges { display:flex; gap:6px; flex-wrap:wrap; margin:6px 0; }
.badge { font-size:12px; padding:2px 10px; border-radius:10px; background:#eef; color:#556; }
.badge.type-公测 { background:#e8f5e9; color:#2e7d32; }
    .badge.type-内测 { background:#ffebee; color:#c62828; }
.badge.type-新版本 { background:#e3f2fd; color:#1565c0; }
.badge.type-资料片 { background:#f3e5f5; color:#7b1fa2; }
.badge.type-日常更新 { background:#eceff1; color:#546e7a; }
.badge.type-首发 { background:#e8f5e9; color:#2e7d32; }
    .badge.type-封测 { background:#fff8e1; color:#f9a825; }
.badge.need-code { background:#ffebee; color:#c62828; }
.badge.wiped { background:#fce4ec; color:#880e4f; }
.meta { font-size:13px; color:#999; margin:4px 0; }
.log { font-size:13px; color:#444; background:#f8f8f8; padding:8px 10px; border-radius:8px; margin:6px 0; line-height:1.5; }
.link { font-size:12px; color:#667eea; word-break:break-all; margin:3px 0; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.empty-day { text-align:center; padding:20px 0; color:#ccc; font-size:13px; }
.modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:100; justify-content:center; align-items:flex-start; padding-top:50px; }
.modal-overlay.show { display:flex; }
.modal { background:#fff; border-radius:16px 16px 0 0; width:100%; max-width:500px; max-height:80vh; overflow-y:auto; padding:18px 20px; margin:0 12px; box-shadow:0 -4px 20px rgba(0,0,0,0.15); }
.modal h2 { font-size:16px; margin-bottom:10px; }
.modal-item { padding:8px 0; border-bottom:1px solid #f0f0f0; }
.modal-item:last-child { border-bottom:none; }
.modal-item .mi-date { font-size:12px; color:#667eea; font-weight:600; }
.modal-item .mi-info { font-size:12px; color:#555; margin:2px 0; }
.modal-close { margin-top:10px; width:100%; padding:10px; border:none; border-radius:8px; background:#f0f0f0; font-size:14px; cursor:pointer; }
.tabs { display:flex; gap:0; background:rgba(255,255,255,0.15); border-radius:10px; padding:3px; }
.tab { padding:5px 14px; border:none; border-radius:8px; background:transparent; color:rgba(255,255,255,0.8); cursor:pointer; font-size:13px; font-weight:500; transition:all 0.2s; }
.tab:hover { color:#fff; }
.tab.active { background:#fff; color:#667eea; font-weight:600; }
.sub-tabs { display:flex; align-items:center; gap:4px; padding:8px 20px 0; max-width:960px; margin:0 auto; }
.sub-tab { font-size:12px; padding:4px 12px; border-radius:6px 6px 0 0; cursor:pointer; color:#888; background:#eee; border:1px solid #ddd; border-bottom:none; user-select:none; }
.sub-tab.active { background:#fff; color:#333; font-weight:600; border-color:#ccc; }
.export-csv-btn { margin-left:auto; font-size:12px; padding:4px 14px; border-radius:6px; cursor:pointer; background:#43a047; color:#fff; font-weight:500; user-select:none; }
.export-csv-btn:hover { background:#388e3c; }
.view { display:none; }
.view.active { display:block; }
.schedule-container { height:calc(100vh - 130px); overflow-y:auto; padding:16px 20px; max-width:960px; margin:0 auto; white-space:normal; }
.month-group { margin-bottom:24px; }
.month-title { font-size:18px; font-weight:600; color:#667eea; padding:8px 0 12px; border-bottom:2px solid #667eea; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
.month-title .count { font-size:13px; color:#999; font-weight:400; }
.day-group { margin-bottom:8px; }
.day-title { font-size:14px; font-weight:600; color:#555; padding:4px 0 6px; }
.schedule-container .card { cursor:default; }
.schedule-container .card .se { margin-top:6px; background:#fafbfc; border-radius:8px; padding:6px 8px; }
.schedule-container .card .se-row { display:flex; align-items:center; gap:4px; flex-wrap:wrap; }
.schedule-container .card .se-row label { font-size:10px; color:#999; white-space:nowrap; }
.schedule-container .card .se-row select { font-size:11px; padding:1px 4px; border:1px solid #ddd; border-radius:4px; background:#fff; }
.schedule-container .card .se-row .se-input { font-size:11px; padding:1px 4px; border:1px solid #ddd; border-radius:4px; width:90px; }
.schedule-container .card .se-row .fd { font-size:11px; padding:1px 4px; border:1px solid #ddd; border-radius:4px; width:108px; }
.move-btn { display:inline-block; font-size:11px; padding:3px 10px; border-radius:6px; cursor:pointer; font-weight:500; user-select:none; }
.move-btn:hover { opacity:0.85; }
.move-to-schedule { background:#e8f5e9; color:#2e7d32; border:1px solid #c8e6c9; }
.move-to-review { background:#fff3e0; color:#e65100; border:1px solid #ffe0b2; }
.wl-header { display:flex; gap:8px; padding:10px 0; align-items:center; flex-wrap:wrap; }
.wl-header .wl-btn { font-size:13px; padding:7px 18px; border:none; border-radius:8px; cursor:pointer; font-weight:500; }
.wl-header .wl-btn.add { background:#667eea; color:#fff; }
.wl-header .wl-btn.add:hover { background:#7b93ff; }
.wl-list { display:flex; flex-direction:column; gap:2px; }
.wl-item { display:flex; align-items:center; gap:8px; padding:6px 10px; background:#fff; border-radius:6px; box-shadow:0 1px 2px rgba(0,0,0,0.05); font-size:13px; }
.wl-item:hover { background:#f8f8ff; }
.wl-item .wl-name-input { flex:1; border:1px solid transparent; border-radius:4px; padding:2px 6px; font-size:13px; outline:none; background:transparent; color:#333; font-weight:500; }
.wl-item .wl-name-input:hover { border-color:#ddd; background:#fafafa; }
.wl-item .wl-name-input:focus { border-color:#667eea; background:#fff; }
.wl-item .wl-history-btn { font-size:14px; cursor:pointer; color:#999; padding:0 4px; line-height:1; }
.wl-item .wl-history-btn:hover { color:#667eea; }
.wl-item .wl-del-btn { font-size:16px; cursor:pointer; color:#ccc; padding:0 4px; line-height:1; font-weight:300; }
.wl-item .wl-del-btn:hover { color:#e53935; }
.wl-item .wl-id-input { width:80px; border:1px solid transparent; border-radius:4px; padding:2px 6px; font-size:11px; outline:none; background:transparent; color:#999; font-family:monospace; }
.wl-item .wl-id-input:hover { border-color:#ddd; background:#fafafa; }
.wl-item .wl-id-input:focus { border-color:#667eea; background:#fff; color:#333; }
.wl-count { font-size:12px; color:#999; padding:4px 0; }
.scrape-btn { font-size:12px; padding:5px 14px; border:none; border-radius:8px; cursor:pointer; background:#e8f5e9; color:#2e7d32; font-weight:600; }
.scrape-btn:hover { background:#c8e6c9; }
.scrape-btn:disabled { opacity:0.5; cursor:not-allowed; }
.scrape-panel { position:fixed; bottom:0; left:0; right:0; background:#fff; border-top:2px solid #667eea; z-index:200; box-shadow:0 -4px 20px rgba(0,0,0,0.1); max-height:40vh; display:flex; flex-direction:column; }
.scrape-header { display:flex; justify-content:space-between; align-items:center; padding:8px 16px; background:#f5f5fb; font-size:13px; font-weight:600; flex-shrink:0; }
.scrape-close { font-size:12px; color:#999; cursor:pointer; padding:4px 8px; }
.scrape-close:hover { color:#333; }
.scrape-body { flex:1; overflow-y:auto; padding:8px 16px; font-size:12px; font-family:Consolas,'Courier New',monospace; line-height:1.5; background:#1e1e2e; color:#cdd6f4; white-space:pre-wrap; }
</style>
</head>
 <body>
<div class="header">
  <div class="tabs">
    <span class="tab active" data-view="calendar" onclick="switchView('calendar')">📅 日历</span>
    <span class="tab" data-view="schedule" onclick="switchView('schedule')">📋 测试表</span>
    <span class="tab" data-view="review" onclick="switchView('review')">✏️ 待审核</span>
    <span class="tab" data-view="whitelist" onclick="switchView('whitelist')">📋 白名单</span>
    <span class="tab" data-view="settings" onclick="switchView('settings')">⚙ 设置</span>
  </div>
  <div class="save-area" id="saveArea">
    <span class="save-btn" id="saveBtn" onclick="saveAll()">保存</span>
    <span class="scrape-btn" id="scrapeBtn" onclick="startScrape()">采集</span>
  </div>
</div>
<div class="scrape-panel" id="scrapePanel" style="display:none">
  <div class="scrape-header">
    <span id="scrapeTitle">采集进度</span>
    <span class="scrape-close" onclick="closeScrapePanel()">关闭</span>
  </div>
  <div class="scrape-body" id="scrapeLog"></div>
</div>
<div class="filter-bar" id="filterBar">
  <input type="text" id="searchInput" placeholder="搜索游戏..." oninput="onSearchInput()">
  <span style="font-size:12px;color:#999;flex-shrink:0" id="viewStats"></span>
  <input type="file" id="gzhFileInput" accept=".xls,.xlsx" style="display:none" onchange="uploadGZHFile(event)">
  <button class="btn-sm" id="importGzhBtn" onclick="document.getElementById('gzhFileInput').click()" style="background:#4caf50;color:#fff;padding:4px 10px;font-size:12px;border:none;border-radius:6px;cursor:pointer;white-space:nowrap">导入公众号</button>
  <input type="date" id="reviewStartDate" style="padding:4px 8px;font-size:12px;border:1px solid #ddd;border-radius:6px"> <span style="font-size:12px;color:#999">~</span> <input type="date" id="reviewEndDate" style="padding:4px 8px;font-size:12px;border:1px solid #ddd;border-radius:6px"> <button class="btn-sm" onclick="startDateReview()" style="background:#e74c3c;color:#fff;padding:4px 10px;font-size:12px;border:none;border-radius:6px;cursor:pointer;white-space:nowrap">AI审查所选日期</button><button onclick="exportEvents()" style="padding:4px 12px;background:#2196F3;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:12px;margin-left:4px">导出JSON</button> <span id="reviewStatus" style="font-size:12px;color:#999;margin-left:4px;display:none"></span> <button class="btn-sm" onclick="showAddEventModal()" style="background:#ff9800;color:#fff;padding:4px 10px;font-size:12px;border:none;border-radius:6px;cursor:pointer;white-space:nowrap">+ 新增节点</button>
</div>
<div class="view active" id="viewCalendar">
  <div class="container" id="container"></div>
</div>
<div class="view" id="viewSchedule">
  <div class="sub-tabs" id="scheduleSubTabs">
    <span class="sub-tab active" data-sub="all" onclick="switchScheduleSub('all')">全部测试表</span>
    <span class="sub-tab" data-sub="exported" onclick="switchScheduleSub('exported')">已导出测试表</span>
    <span class="sub-tab" data-sub="new" onclick="switchScheduleSub('new')">新增测试表</span>
    <span class="export-csv-btn" id="exportCsvBtn" onclick="exportScheduleCsv()">导出 CSV</span>
  </div>
  <div class="schedule-container" id="scheduleContainer"></div>
</div>
<div class="view" id="viewReview">
  <div class="container" id="reviewContainer"></div>
</div>
<div class="view" id="viewWhitelist">
  <div class="schedule-container" id="whitelistContainer"></div>
</div>
<div class="view" id="viewSettings">
  <div class="settings-container" id="settingsContainer" style="padding:16px;max-width:600px;margin:0 auto">
    <div style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,0.06)">
      <h3 style="margin:0 0 12px;font-size:15px">API 配置</h3>
      <div id="settingsForm"></div>
      <div style="margin-top:12px;text-align:right">
        <span class="save-btn" onclick="saveSettings()">保存设置</span>
        <span id="settingsStatus" style="margin-left:8px;font-size:12px;color:#999"></span>
      </div>
    </div>
  </div>
</div>
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <h2 id="modalTitle">--</h2>
    <div id="modalBody"></div>
    <button class="modal-close" onclick="closeModal()">关闭</button>
  </div>
</div>
<div class="modal-overlay" id="addEventOverlay" style="display:none">
  <div class="modal" style="max-width:520px">
    <h2>新增节点</h2>
    <div style="padding:12px 0">
      <div style="margin-bottom:10px">
        <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">游戏名称 *</label>
        <input type="text" id="addEventGame" placeholder="输入游戏名称" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box" oninput="onGameNameInput()" autocomplete="off">
        <div id="addEventGameSuggestions" style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;max-height:160px;overflow-y:auto;display:none;position:absolute;background:#fff;width:calc(100% - 2px);z-index:100;box-shadow:0 4px 12px rgba(0,0,0,0.1)"></div>
      </div>
      <div style="margin-bottom:10px;position:relative">
        <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">测试名称 *</label>
        <input type="text" id="addEventTestName" placeholder="例如：拂晓测试" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:10px">
        <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">测试时间 *</label>
        <input type="date" id="addEventDate" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:10px">
        <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">测试类型</label>
        <select id="addEventType" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;background:#fff">
          <option value="内测">内测</option>
          <option value="公测">公测</option>
          <option value="封测">封测</option>
          <option value="新版本">新版本</option>
          <option value="资料片">资料片</option>
          <option value="日常更新">日常更新</option>
        </select>
      </div>
      <div style="display:flex;gap:12px;margin-bottom:10px">
        <div style="flex:1">
          <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">需要激活码</label>
          <select id="addEventNeedCode" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;background:#fff">
            <option value="">--</option>
            <option value="是">是</option>
            <option value="否">否</option>
          </select>
        </div>
        <div style="flex:1">
          <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">是否删档</label>
          <select id="addEventIsWiped" style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;background:#fff">
            <option value="">--</option>
            <option value="是">是</option>
            <option value="否">否</option>
          </select>
        </div>
      </div>
      <div style="margin-bottom:10px">
        <label style="font-size:13px;color:#666;display:block;margin-bottom:3px">来源链接（可选）</label>
        <input type="text" id="addEventLink" placeholder="https://..." style="width:100%;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box">
      </div>
      <div id="addEventError" style="color:#e74c3c;font-size:13px;display:none;margin-bottom:8px"></div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button onclick="closeAddEventModal()" style="padding:7px 20px;border:1px solid #ddd;border-radius:8px;cursor:pointer;background:#fff;font-size:13px">取消</button>
      <button onclick="submitAddEvent()" id="addEventSubmitBtn" style="padding:7px 20px;border:none;border-radius:8px;cursor:pointer;background:#ff9800;color:#fff;font-size:13px;font-weight:500">提交</button>
    </div>
  </div>
</div>


<script>
var DATA = """ + events_json + r""";

const API_URL = """ + api_url_value + r""";
const API_BASE = (window.location.protocol === 'file:') ? API_URL : window.location.origin;
const WHITELIST = """ + whitelist_json + r""";
""" + pending_save + r"""
 
function startDateReview(){
  var sd=document.getElementById('reviewStartDate').value;
  var ed=document.getElementById('reviewEndDate').value;
  if(!sd||!ed){alert('请选择日期');return}
  if(!confirm('审查 '+sd+' 至 '+ed+' 的节点？'))return;
  var st=document.getElementById('reviewStatus');
  st.style.display='inline';st.textContent='审查中...';st.style.color='#e74c3c';
  fetch(API_BASE+'/api/review_range',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({start_date:sd,end_date:ed})
  }).then(function(r){return r.json()}).then(function(d){
    if(d.ok){
      var r=d.results||[];
      var ok=r.filter(function(x){return x.verdict==='confirmed'}).length;
      var bad=r.filter(function(x){return x.verdict==='contradicted'}).length;
      var unk=r.filter(function(x){return x.verdict==='unverified'}).length;
      window._lastReviewResults=r;
      st.innerHTML=r.length+'个完成 | OK:'+ok+' 矛盾:'+bad+' 存疑:'+unk+' <span onclick=\'showReviewReport()\' style=\'cursor:pointer;color:#2196F3;text-decoration:underline;margin-left:8px\'>查看报告</span>';
      st.style.color='#27ae60';
        try{refreshData();}catch(e){console.log("refresh error",e);}
    }else{st.textContent=(d.error||'失败');st.style.color='#e74c3c'}
  }).catch(function(e){st.textContent='网络错误';st.style.color='#e74c3c'})
}



function showReviewReport(){
    var r=window._lastReviewResults||[];
    if(!r||!r.length){alert("\u65e0\u5ba1\u67e5\u6570\u636e");return}
    var sd=document.getElementById("reviewStartDate");
    var ed=document.getElementById("reviewEndDate");
    var cats={confirmed:[],unverified:[],contradicted:[]};
    var labels={confirmed:"\u2705 \u5408\u89c4\u8282\u70b9",unverified:"\u26a0\ufe0f \u5b58\u7591\u8282\u70b9",contradicted:"\u274c \u95ee\u9898\u8282\u70b9"};
    var vlabels={confirmed:"\u901a\u8fc7",unverified:"\u5b58\u7591",contradicted:"\u95ee\u9898"};
    r.forEach(function(x){if(cats[x.verdict])cats[x.verdict].push(x)});
    
    // Build report text for copying
    function buildReportText(){
        var txt="\u5ba1\u67e5\u62a5\u544a - "+(sd?sd.value:"")+" \u81f3 "+(ed?ed.value:"")+" | \u5171 "+r.length+" \u4e2a\u8282\u70b9\n\n";
        ["confirmed","unverified","contradicted"].forEach(function(v){
            var items=cats[v];if(!items||!items.length)return;
            txt+=labels[v]+" ("+items.length+")\n";
            items.forEach(function(x){
                txt+="  ["+vlabels[v]+"] "+x.game+" - "+x.test_name+"\n";
                txt+="    \u65e5\u671f: "+x.date+" | \u7c7b\u578b: "+(x.test_type||"")+" | \u6765\u6e90: "+(x.source||"-")+"\n";
                if(x.reasoning)txt+="    \u8bf4\u660e: "+x.reasoning+"\n";
                txt+="\n";
            });
        });
        return txt;
    }
    
    function copyReport(){
        var txt=buildReportText();
        if(navigator.clipboard&&navigator.clipboard.writeText){
            navigator.clipboard.writeText(txt).then(function(){
                var btn=document.getElementById("copyReportBtn");
                btn.textContent="\u2713 \u5df2\u590d\u5236";btn.style.background="#c8e6c9";
                setTimeout(function(){btn.textContent="\u590d\u5236\u62a5\u544a";btn.style.background="#e3f2fd"},2000);
            });
        }else{
            var ta=document.createElement("textarea");ta.value=txt;
            document.body.appendChild(ta);ta.select();document.execCommand("copy");
            document.body.removeChild(ta);
        }
    }
    
    var h="<div style=\"position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.5);z-index:99999;overflow:auto;display:flex;align-items:center;justify-content:center\">";
    h+="<div style=\"background:#fff;max-width:800px;width:90%;border-radius:12px;padding:24px;box-shadow:0 8px 32px rgba(0,0,0,0.2);max-height:80vh;overflow-y:auto;position:relative\">";
    h+="<h2 style=\"margin:0 0 4px\">\ud83d\udccb \u5ba1\u67e5\u62a5\u544a</h2>";
    h+='<p style="color:#666;font-size:13px;margin:0 0 12px">'+(sd?sd.value:"")+" \u81f3 "+(ed?ed.value:"")+" | \u5171 "+r.length+" \u4e2a\u8282\u70b9</p>";
    h+='<div style="position:absolute;top:12px;right:12px;display:flex;gap:6px">';
    h+='<button id="copyReportBtn" onclick="copyReport()" style="padding:4px 12px;border:none;border-radius:6px;background:#e3f2fd;color:#1565c0;cursor:pointer;font-size:13px">\ud83d\udcc4 \u590d\u5236\u62a5\u544a</button>';
    h+='<button onclick="this.parentElement.parentElement.parentElement.remove()" style="padding:4px 12px;border:none;border-radius:6px;background:#f0f0f0;cursor:pointer;font-size:13px">\u2716</button>';
    h+="</div>";
    
    ["confirmed","unverified","contradicted"].forEach(function(v){
        var items=cats[v];if(!items||!items.length)return;
        var cl={confirmed:"#e8f5e9",unverified:"#fef5e7",contradicted:"#fdecea"};
        var bc={confirmed:"#a5d6a7",unverified:"#fad7a0",contradicted:"#f5b7b1"};
        h+="<div style=\"background:"+cl[v]+";border:1px solid "+bc[v]+";border-radius:8px;padding:12px 16px;margin:0 0 12px\">";
        h+="<h3 style=\"margin:0 0 8px;font-size:15px\">"+labels[v]+" ("+items.length+")</h3>";
        items.forEach(function(x){
            h+="<div style=\"padding:8px 0;border-top:1px solid "+bc[v]+"\">";
            h+="<b>"+x.game+" - "+x.test_name+"</b>";
            h+="<div style=\"font-size:12px;color:#666;margin:2px 0\">\ud83d\udcc5 "+x.date+" | \ud83d\udcca "+(x.test_type||"")+" | \ud83d\udd17 "+(x.source||"-")+"</div>";
            if(x.reasoning)h+="<div style=\"font-size:12px;color:#333;margin:4px 0;background:#fff;padding:6px;border-radius:4px\">\ud83d\udcdd "+x.reasoning+"</div>";
            h+="<div style=\"font-size:11px;color:#999\">\ud83d\udcca \u4fe1\u5ea6: "+(x.confidence||"-")+"</div>";
            h+="</div>";
        });
        h+="</div>";
    });
    h+="</div></div>";
    var d=document.createElement("div");d.innerHTML=h;document.body.appendChild(d);
}
function uploadGZHFile(event) {
  const btn = document.getElementById('importGzhBtn');
  if (!btn) return;
  const file = event.target.files[0];
  if (!file) return;
  btn.textContent = '上传中...';
  btn.style.opacity = '0.5';
  const fd = new FormData();
  fd.append('file', file);
  fetch(API_BASE + '/api/upload-public-account', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      if (data.ok && data.count > 0) {
        btn.textContent = '✅ ' + (data.count || 0) + ' 条';
        refreshData();
      } else if (data.ok) {
        btn.textContent = '✅ 无新数据';
      } else {
        btn.textContent = '❌ ' + (data.error || '失败');
      }
      setTimeout(() => { btn.textContent = '导入公众号'; btn.style.opacity = '1'; }, 3000);
    })
    .catch(() => {
      btn.textContent = '导入失败';
      setTimeout(() => { btn.textContent = '导入公众号'; btn.style.opacity = '1'; }, 2000);
    });
  event.target.value = '';
}

function showAddEventModal() {
  document.getElementById('addEventOverlay').style.display = 'flex';
  document.getElementById('addEventGame').value = '';
  document.getElementById('addEventTestName').value = '';
  document.getElementById('addEventDate').value = new Date().toISOString().slice(0,10);
  document.getElementById('addEventType').value = '内测';
  document.getElementById('addEventNeedCode').value = '';
  document.getElementById('addEventIsWiped').value = '';
  document.getElementById('addEventLink').value = '';
  document.getElementById('addEventError').style.display = 'none';
  document.getElementById('addEventGameSuggestions').style.display = 'none';
  document.getElementById('addEventSubmitBtn').disabled = false;
  document.getElementById('addEventSubmitBtn').textContent = '提交';
  document.getElementById('addEventGame').focus();
}
function showReviewDetail(id){var e=DATA.find(function(x){return x.id===id});if(!e||!e.review_verdict)return;var t={'confirmed':'已核实','contradicted':'数据异常','unverified':'存疑'};var c={'confirmed':'#27ae60','contradicted':'#e74c3c','unverified':'#f39c12'};document.getElementById('modalTitle').textContent='['+t[e.review_verdict]+'] 审查结果';var h='<div style="padding:10px;font-size:14px;line-height:1.6">';h+='<div style="color:'+c[e.review_verdict]+';font-size:16px;font-weight:600;margin-bottom:8px">'+t[e.review_verdict]+'</div>';h+='<div style="color:#666;font-size:12px;margin:4px 0">信赪度: '+(e.review_confidence||'')+'</div>';h+='<div style="color:#666;font-size:12px;margin:4px 0">审查时间: '+(e.review_date||'')+'</div>';if(e.review_reasoning)h+='<div style="margin-top:8px;padding:8px;background:#f5f5f5;border-radius:6px;color:#333;font-size:13px">'+(e.review_reasoning||'')+'</div>';h+='</div>';document.getElementById('modalBody').innerHTML=h;document.getElementById('modalOverlay').style.display='flex'}

function closeAddEventModal() {
  document.getElementById('addEventOverlay').style.display = 'none';
}
function onGameNameInput() {
  const q = document.getElementById('addEventGame').value.trim();
  const sug = document.getElementById('addEventGameSuggestions');
  if (!q) { sug.style.display = 'none'; return; }
  const ql = q.toLowerCase();
  const games = DATA.map(d => d.display_name || d.clean_name).filter((v,i,a) => a.indexOf(v)===i);
  const matched = games.filter(g => g.toLowerCase().includes(ql)).slice(0, 8);
  if (matched.length === 0) { sug.style.display = 'none'; return; }
  sug.innerHTML = matched.map(g => '<div onclick="selectGame(\''+g.replace(/'/g,"\\'")+'\')" style="padding:6px 10px;cursor:pointer;font-size:13px;border-bottom:1px solid #eee">'+esc(g)+'</div>').join('');
  sug.style.display = 'block';
}
function selectGame(name) {
  document.getElementById('addEventGame').value = name;
  document.getElementById('addEventGameSuggestions').style.display = 'none';
}
function submitAddEvent() {
  const game = document.getElementById('addEventGame').value.trim();
  const testName = document.getElementById('addEventTestName').value.trim();
  const testTime = document.getElementById('addEventDate').value;
  const testType = document.getElementById('addEventType').value;
  const needCode = document.getElementById('addEventNeedCode').value;
  const isWiped = document.getElementById('addEventIsWiped').value;
  const link = document.getElementById('addEventLink').value.trim();
  const errDiv = document.getElementById('addEventError');
  if (!game) { errDiv.textContent = '请输入游戏名称'; errDiv.style.display = 'block'; return; }
  if (!testName) { errDiv.textContent = '请输入测试名称'; errDiv.style.display = 'block'; return; }
  if (!testTime) { errDiv.textContent = '请选择测试时间'; errDiv.style.display = 'block'; return; }
  errDiv.style.display = 'none';
  const btn = document.getElementById('addEventSubmitBtn');
  btn.disabled = true; btn.textContent = '提交中...';
  fetch(API_BASE + '/api/events/add', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      game_name: game,
      test_name: testName,
      test_time: testTime,
      test_type: testType,
      need_code: needCode || null,
      is_wiped: isWiped || null,
      link: link || null
    })
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      closeAddEventModal();
      refreshData();
    } else {
      errDiv.textContent = data.error || '提交失败';
      errDiv.style.display = 'block';
      btn.disabled = false; btn.textContent = '提交';
    }
  }).catch(e => {
    errDiv.textContent = '网络错误: '+e.message;
    errDiv.style.display = 'block';
    btn.disabled = false; btn.textContent = '提交';
  });
}
// Also close modal on overlay click
document.addEventListener('click', function(e) {
  const ov = document.getElementById('addEventOverlay');
  if (ov && ov.style.display === 'flex' && e.target === ov) closeAddEventModal();
});

const DAY_MS = 86400000;
const STATUS_BG = {'正常':'#e8f5e9','新增':'#e3f2fd','待审':'#fff3e0','弃用':'#fce4ec'};
const STATUS_COLOR = {'正常':'#2e7d32','新增':'#1565c0','待审':'#e65100','弃用':'#c62828'};

function parseDate(s) {
  if (!s) return null;
  let m = s.match(/(\d{4})\/(\d{1,2})\/(\d{1,2})/);
  if (m) return new Date(+m[1],+m[2]-1,+m[3]);
  m = s.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return new Date(+m[1],+m[2]-1,+m[3]);
  return null;
}
function fmtDate(d) { return d.getFullYear()+'/'+((d.getMonth()+1)+'').padStart(2,'0')+'/'+(d.getDate()+'').padStart(2,'0'); }
function esc(s) { if(!s)return ''; return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

const weekdays = ['日','一','二','三','四','五','六'];
let allEvents = DATA;
    allEvents.forEach(function(e){var s=localStorage.getItem('mr_'+e.id);if(s!==null)e.manual_reviewed=parseInt(s);});

// build date-indexed map
let allDates = {};
for (const e of allEvents) {
  let d = parseDate(e.date);
  if (!d) continue;
  let key = fmtDate(d);
  if (!allDates[key]) allDates[key] = [];
  allDates[key].push(e);
}
let sortedKeys = Object.keys(allDates).sort();
let currentView = 'calendar';

const COL_FILTERS = {};
function getCF(key) { if (!COL_FILTERS[key]) COL_FILTERS[key] = { status: [], type: [], source: [] }; return COL_FILTERS[key]; }
const FILTER_CHIPS = { status: ['正常','新增','待审','弃用'], type: ['公测','内测','新版本','资料片','日常更新','封测'], source: ['好游快爆','Steam','公众号','TapTap'] };
let openFilterCols = new Set();

function toggleChip(key, cat, val) {
  const cf = getCF(key);
  const idx = cf[cat].indexOf(val);
  if (idx > -1) cf[cat].splice(idx, 1);
  else cf[cat].push(val);
  render(document.getElementById('searchInput').value.trim());
}
function toggleColFilter(e, key) {
  e.stopPropagation();
  if (openFilterCols.has(key)) openFilterCols.delete(key);
  else openFilterCols.add(key);
  render(document.getElementById('searchInput').value.trim());
}
function clearColFilter(key) {
  COL_FILTERS[key] = { status: [], type: [], source: [] };
  openFilterCols.delete(key);
  render(document.getElementById('searchInput').value.trim());
}

function switchView(view) {
  currentView = view;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view' + view.charAt(0).toUpperCase() + view.slice(1)));
  const stats = document.getElementById('viewStats');
  const search = document.getElementById('searchInput').value.trim();
  if (view === 'calendar') {
    stats.textContent = '';
    render(search);
  } else if (view === 'schedule') {
    stats.textContent = '正常 + 待审';
    renderTestSchedule(search);
  } else if (view === 'review') {
    stats.textContent = '新增·未匹配白名单 + 已移除';
    renderReview(search);
  } else if (view === 'whitelist') {
    stats.textContent = '';
    renderWhitelist(search);
  } else if (view === 'settings') {
    stats.textContent = '';
    loadSettingsUI();
  }
}

function onSearchInput() {
  const search = document.getElementById('searchInput').value.trim();
  if (currentView === 'calendar') render(search);
  else if (currentView === 'schedule') renderTestSchedule(search);
  else if (currentView === 'review') renderReview(search);
  else if (currentView === 'whitelist') renderWhitelist(search);
}

function inWhitelist(name) {
  return WHITELIST.some(w => name.includes(w.name) || w.name.includes(name));
}

let scheduleSub = 'all';

function switchScheduleSub(sub) {
  scheduleSub = sub;
  document.querySelectorAll('#scheduleSubTabs .sub-tab').forEach(t => t.classList.toggle('active', t.dataset.sub === sub));
  renderTestSchedule(document.getElementById('searchInput').value.trim());
}

function exportScheduleCsv() {
  const today = new Date(); today.setHours(0,0,0,0);
  const start = new Date(today);
  const end = new Date(today); end.setDate(end.getDate() + 45);
  let events = allEvents.filter(e => {
    if (e.removed) return false;
    if (!inWhitelist(e.clean)) return false;
    if (e.status === '正常' || e.status === '待审' || e.status === '新增') return true;
    return false;
  }).filter(e => {
    const d = parseDate(e.date);
    return d && d >= start && d <= end;
  }).filter(e => !e.exported);
  // Build CSV
  const headers = ['游戏名称','游戏ID','测试名称','测试时间','测试类型','状态','需要激活码','是否删档','是否正式运营','评价数','下载/预约数','来源','链接','日志'];
  const rows = events.map(e => {
    const wlEntry = WHITELIST.find(w => e.clean.includes(w.name) || w.name.includes(e.clean));
    const gid = wlEntry ? wlEntry.id : '';
    return [e.game, gid, e.test_name, e.date, e.test_type, e.status, e.need_code, e.is_wiped, e.is_formal, e.rating, e.download, e.source, e.url, e.log];
  });
  let csv = '\uFEFF'; // BOM for Excel
  csv += headers.join(',') + '\n';
  for (const row of rows) {
    csv += row.map(v => '"' + (v || '').replace(/"/g,'""') + '"').join(',') + '\n';
  }
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '测试表_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
  // Mark all exported events
  const ids = events.filter(e => !e.exported).map(e => e.id);
  if (ids.length && API_URL) {
    Promise.all(ids.map(id =>
      fetch(API_BASE + '/api/batch_update', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify([{id, exported:1}])
      })
    )).then(() => {
      events.forEach(e => { if (!e.exported) e.exported = 1; });
      renderTestSchedule(document.getElementById('searchInput').value.trim());
    }).catch(() => {});
  }
}

function renderTestSchedule(search) {
  const container = document.getElementById('scheduleContainer');
  container.innerHTML = '';
  const today = new Date(); today.setHours(0,0,0,0);
  let testEvents = allEvents.filter(e => {
    if (e.removed) return false;
    if (!inWhitelist(e.clean)) return false;
    if (e.status === '正常' || e.status === '待审' || e.status === '新增') return true;
    return false;
  });
  const mode = scheduleSub;
  if (mode === 'new') {
    const start = new Date(today); start.setDate(start.getDate() - 1);
    const end = new Date(today); end.setDate(end.getDate() + 45);
    testEvents = testEvents.filter(e => {
      const d = parseDate(e.date);
      return d && d >= start && d <= end;
    }).filter(e => !e.exported);
  } else if (mode === 'exported') {
    testEvents = testEvents.filter(e => e.exported);
  }
  if (!testEvents.length) {
    container.innerHTML = '<div style="text-align:center;padding:40px;color:#999">无匹配结果</div>';
    return;
  }
  const grouped = {};
  for (const e of testEvents) {
    const d = parseDate(e.date);
    if (!d) continue;
    const monthKey = d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0');
    const dayKey = fmtDate(d);
    if (!grouped[monthKey]) grouped[monthKey] = {};
    if (!grouped[monthKey][dayKey]) grouped[monthKey][dayKey] = [];
    grouped[monthKey][dayKey].push(e);
  }
  const months = Object.keys(grouped).sort();
  for (const mk of months) {
    const days = grouped[mk];
    let monthTotal = 0;
    Object.values(days).forEach(arr => monthTotal += arr.length);
    let html = '<div class="month-group"><div class="month-title">'+mk+' <span class="count">('+monthTotal+' 条)</span></div>';
    const dayKeys = Object.keys(days).sort();
    for (const dk of dayKeys) {
      html += '<div class="day-group"><div class="day-title">'+dk+'</div>';
      for (const e of days[dk].sort((a,b)=>a.test_name.localeCompare(b.test_name))) {
        if (search && !e.game.includes(search) && !e.clean.includes(search)) continue;
        html += buildCard(e, 'schedule');
      }
      html += '</div>';
    }
    html += '</div>';
    container.innerHTML += html;
  }
}

function renderReview(search) {
  const container = document.getElementById('reviewContainer');
  container.innerHTML = '';
  const today = new Date(); today.setHours(0,0,0,0);
  const cutoff = new Date(today); cutoff.setDate(cutoff.getDate() - 1);
    const reviewEvents = allEvents.filter(e => {
    if (e.removed) return true;
    if (e.status !== '新增' && e.status !== '待审') return false;
    if (inWhitelist(e.clean)) return false;
    if (e.source_type === 'scrape') {
      const sd = e.scrape_date ? new Date(e.scrape_date) : null;
      if (!sd) return false;
      sd.setHours(0,0,0,0);
      if (sd < cutoff) return false;
    }
    return true;
  });
    if (!reviewEvents.length) {
    container.innerHTML = '<div style="text-align:center;padding:40px;color:#999">近1天无新增待审核记录</div>';
    return;
  }
  const grouped = {};
  for (const e of reviewEvents) {
    const d = parseDate(e.date);
    if (!d) continue;
    const key = fmtDate(d);
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(e);
  }
  const sortedKeys = Object.keys(grouped).sort();
  for (const key of sortedKeys) {
    const d = parseDate(key);
    let html = '<div class="day-col"><div class="day-header">'+(d.getMonth()+1)+'月'+d.getDate()+'日 <span class="weekday">周'+'日一二三四五六'.charAt(d.getDay())+'</span><span class="count">'+grouped[key].length+' 条</span></div>';
    for (const e of grouped[key].sort((a,b)=>a.test_name.localeCompare(b.test_name))) {
      if (search && !e.game.includes(search) && !e.clean.includes(search)) continue;
      html += buildCard(e, 'review');
    }
    html += '</div>';
    container.innerHTML += html;
  }
}

let wlGames = [];
let wlSaveTimer = null;

function renderWhitelist(search) {
  const container = document.getElementById('whitelistContainer');
  container.innerHTML = '';
  let list = wlGames.length ? wlGames : [...WHITELIST];
  if (!wlGames.length) wlGames = [...WHITELIST];
  if (search) list = list.filter(n => n.name.includes(search));
  let html = '<div class="wl-header">';
  html += '<span class="wl-btn add" onclick="showAddWhitelistModal()">+ 添加游戏</span>';
  if (!API_URL) html += '<span style="font-size:12px;color:#e65100;margin-left:8px">⚠ 需 --serve 启动 API</span>';
  html += '</div>';
  html += '<div class="wl-count">共 ' + wlGames.length + ' 个游戏</div>';
  html += '<div class="wl-list">';
  for (const entry of list) {
    html += '<div class="wl-item">';
    html += '<input class="wl-name-input" type="text" value="' + esc(entry.name) + '" onchange="wlEditGame(\'' + esc(entry.name) + '\',this.value)">';
    html += '<input class="wl-id-input" type="text" value="' + esc(entry.id || '') + '" onchange="wlEditId(\'' + esc(entry.name) + '\',this.value)" placeholder="ID">';
    html += '<span class="wl-history-btn" onclick="showWhitelistHistory(\'' + esc(entry.name) + '\')">📜</span>';
    html += '<span class="wl-del-btn" onclick="wlDeleteGame(\'' + esc(entry.name) + '\')">×</span>';
    html += '</div>';
  }
  html += '</div>';
  container.innerHTML = html;
}

function showAddWhitelistModal() {
  document.getElementById('modalTitle').textContent = '添加游戏到白名单';
  document.getElementById('modalBody').innerHTML = '<input type="text" id="wlAddName" placeholder="输入游戏名称" style="width:100%;font-size:16px;padding:10px 14px;border:1px solid #ddd;border-radius:10px;outline:none;box-sizing:border-box;margin-bottom:8px" onkeydown="if(event.key===\'Enter\')document.getElementById(\'wlAddId\').focus()"><input type="text" id="wlAddId" placeholder="输入游戏 ID（必填）" style="width:100%;font-size:16px;padding:10px 14px;border:1px solid #ddd;border-radius:10px;outline:none;box-sizing:border-box" onkeydown="if(event.key===\'Enter\')confirmAddWhitelist()"><div style="margin-top:10px;text-align:right"><span class="move-btn move-to-review" onclick="closeModal()" style="margin-right:8px">取消</span><span class="move-btn move-to-schedule" onclick="confirmAddWhitelist()">确认添加</span></div>';
  document.getElementById('modalOverlay').classList.add('show');
  setTimeout(() => { const inp = document.getElementById('wlAddName'); if (inp) inp.focus(); }, 100);
}

function confirmAddWhitelist() {
  const nameInput = document.getElementById('wlAddName');
  const idInput = document.getElementById('wlAddId');
  if (!nameInput) return;
  const name = nameInput.value.trim();
  if (!name) { alert('请输入游戏名称'); nameInput.focus(); return; }
  const id = (idInput ? idInput.value.trim() : '');
  if (!id) { alert('请输入游戏 ID'); if (idInput) idInput.focus(); return; }
  if (!API_URL) { alert('请先运行 --serve 启动 API 服务，否则白名单无法保存'); return; }
  if (wlGames.some(e => e.name === name)) { alert('该游戏已在白名单中'); return; }
  wlGames.push({name: name, id: id});
  syncWhitelist();
  closeModal();
  renderWhitelist(document.getElementById('searchInput').value.trim());
}

function wlEditGame(oldName, newName) {
  newName = newName.trim();
  if (!newName || oldName === newName) return;
  const idx = wlGames.findIndex(e => e.name === oldName);
  if (idx === -1) return;
  if (wlGames.some(e => e.name === newName)) { alert('该游戏已在白名单中'); return; }
  wlGames[idx] = {name: newName, id: wlGames[idx].id};
  syncWhitelist();
}

function wlEditId(name, newId) {
  newId = newId.trim();
  const idx = wlGames.findIndex(e => e.name === name);
  if (idx === -1) return;
  wlGames[idx] = {name: name, id: newId};
  syncWhitelist();
}

function wlDeleteGame(name) {
  const pwd = prompt('输入密码确认删除：');
  if (pwd !== '17173') { alert('密码错误'); return; }
  const idx = wlGames.findIndex(e => e.name === name);
  if (idx === -1) return;
  wlGames.splice(idx, 1);
  syncWhitelist();
  renderWhitelist(document.getElementById('searchInput').value.trim());
}

function syncWhitelist() {
  if (wlSaveTimer) clearTimeout(wlSaveTimer);
  wlSaveTimer = setTimeout(async () => {
    if (!API_URL) return;
    try {
      let resp = await fetch(API_BASE + '/api/whitelist', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({games: wlGames})
      });
      let result = await resp.json();
      if (result.ok) {
        WHITELIST.length = 0;
        wlGames.forEach(n => WHITELIST.push({name: n.name, id: n.id || ''}));
        // 刷新数据，使待审核/测试表同步
        if (API_URL) {
          fetch(API_BASE + '/api/events').then(r => r.json()).then(fresh => {
            allEvents = fresh.map(e => ({
              id: e.id, game: e.display_name, clean: e.clean_name,
              test_name: e.test_name, date: e.test_time, test_type: e.test_type,
              need_code: e.need_code, is_wiped: e.is_wiped, is_formal: e.is_formal, exported: e.exported||0, removed: e.removed_from_schedule||0,
              rating: e.rating, download: e.download_count,
              links: e.tip_links, log: e.log_text,
              source: e.source, url: e.link,
              link_label: e.source, status: e.status || '新增', source_type: e.source_type, scrape_date: e.scrape_date,
        manual_reviewed: e.manual_reviewed||0, merged_source: e.merged_source||''
            }));
            allEvents.forEach(function(e){var s=localStorage.getItem('mr_'+e.id);if(s!==null)e.manual_reviewed=parseInt(s);});
            allDates = {};
            for (const e of allEvents) {
              let d = parseDate(e.date);
              if (!d) continue;
              let key = fmtDate(d);
              if (!allDates[key]) allDates[key] = [];
              allDates[key].push(e);
            }
            sortedKeys = Object.keys(allDates).sort();
            switchView(currentView);
          }).catch(() => {});
        }
      }
    } catch(e) { console.error('白名单保存失败:', e); }
  }, 500);
}

function flattenCfg(obj, prefix='') {
  let entries = [];
  for (const [k, v] of Object.entries(obj)) {
    const pk = prefix ? prefix + '.' + k : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      entries = entries.concat(flattenCfg(v, pk));
    } else {
      entries.push({ key: pk, val: v });
    }
  }
  return entries;
}

function unflattenCfg(flat) {
  const result = {};
  for (const [compKey, val] of Object.entries(flat)) {
    const parts = compKey.split('.');
    let cur = result;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cur[parts[i]]) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = val;
  }
  return result;
}

async function loadSettingsUI() {
  const container = document.getElementById('settingsForm');
  container.innerHTML = '<div style="text-align:center;padding:20px;color:#999">加载中...</div>';
  try {
    let resp = await fetch(API_BASE + '/api/settings');
    let settings = await resp.json();
    let html = '';
    for (const [fname, cfg] of Object.entries(settings)) {
      html += '<div style="margin-bottom:16px;padding:12px;background:#f9f9fb;border-radius:8px">';
      html += '<div style="font-size:13px;font-weight:600;margin-bottom:8px;color:#555">' + esc(fname) + '</div>';
      const flat = flattenCfg(cfg);
      for (const { key, val } of flat) {
        html += '<div style="margin-bottom:6px">';
        html += '<label style="font-size:11px;color:#888;display:block;margin-bottom:2px">' + esc(key) + '</label>';
        html += '<input class="se-input st-input" data-file="' + esc(fname) + '" data-key="' + esc(key) + '" type="' + (key.includes('key')?'password':'text') + '" value="' + esc(String(val)) + '" style="width:100%">';
        html += '</div>';
      }
      html += '</div>';
    }
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = '<div style="text-align:center;padding:20px;color:#c62828">加载失败: ' + e.message + '</div>';
  }
}

async function saveSettings() {
  const btn = document.querySelector('#settingsContainer .save-btn');
  const status = document.getElementById('settingsStatus');
  btn.textContent = '保存中...';
  status.textContent = '';
  try {
    const flatData = {};
    document.querySelectorAll('.st-input').forEach(inp => {
      const fname = inp.dataset.file;
      const key = inp.dataset.key;
      if (!flatData[fname]) flatData[fname] = {};
      flatData[fname][key] = inp.value;
    });
    const data = {};
    for (const [fname, flat] of Object.entries(flatData)) {
      data[fname] = unflattenCfg(flat);
    }
    let resp = await fetch(API_BASE + '/api/settings', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    let result = await resp.json();
    if (result.ok) {
      status.textContent = '✅ 保存成功';
      status.style.color = '#2e7d32';
    } else {
      status.textContent = '❌ ' + (result.error || '保存失败');
      status.style.color = '#c62828';
    }
  } catch(e) {
    status.textContent = '❌ ' + e.message;
    status.style.color = '#c62828';
  }
  btn.textContent = '保存设置';
}

let scrapeTimer = null;

function refreshAllData() {
  if (API_URL) {
    fetch(API_BASE + '/api/events').then(r => r.json()).then(fresh => {
      allEvents = fresh.map(e => ({
        id: e.id, game: e.display_name, clean: e.clean_name,
        test_name: e.test_name, date: e.test_time, test_type: e.test_type,
        need_code: e.need_code, is_wiped: e.is_wiped, is_formal: e.is_formal, exported: e.exported||0, removed: e.removed_from_schedule||0,
        rating: e.rating, download: e.download_count,
        links: e.tip_links, log: e.log_text,
        source: e.source, url: e.link,
        link_label: e.source, status: e.status || '新增', source_type: e.source_type, scrape_date: e.scrape_date,
        manual_reviewed: e.manual_reviewed||0, merged_source: e.merged_source||''
      }));
      // Restore manual_reviewed from localStorage
      allEvents.forEach(function(e){var s=localStorage.getItem('mr_'+e.id);if(s!==null)e.manual_reviewed=parseInt(s);});
      allDates = {};
      for (const e of allEvents) {
        let d = parseDate(e.date);
        if (!d) continue;
        let key = fmtDate(d);
        if (!allDates[key]) allDates[key] = [];
        allDates[key].push(e);
      }
      sortedKeys = Object.keys(allDates).sort();
      switchView(currentView);
    }).catch(() => {});
  }
}

async function startScrape() {
  const btn = document.getElementById('scrapeBtn');
  const panel = document.getElementById('scrapePanel');
  const log = document.getElementById('scrapeLog');
  btn.disabled = true;
  btn.textContent = '采集中...';
  panel.style.display = 'flex';
  log.textContent = '启动采集...\n';
  try {
    let resp = await fetch(API_BASE + '/api/scrape', { method:'POST' });
    let result = await resp.json();
    if (!result.ok) {
      log.textContent += '错误: ' + (result.error || '启动失败') + '\n';
      btn.disabled = false;
      btn.textContent = '采集';
      return;
    }
    pollScrapeStatus();
  } catch(e) {
    log.textContent += '请求失败: ' + e.message + '\n';
    btn.disabled = false;
    btn.textContent = '采集';
  }
}

async function pollScrapeStatus() {
  const log = document.getElementById('scrapeLog');
  const btn = document.getElementById('scrapeBtn');
  let lastLen = 0;
  const poll = async () => {
    try {
      let resp = await fetch(API_BASE + '/api/scrape_status');
      let status = await resp.json();
      if (status.logs && status.logs.length > lastLen) {
        for (let i = lastLen; i < status.logs.length; i++) {
          log.textContent += status.logs[i] + '\n';
        }
        lastLen = status.logs.length;
        log.scrollTop = log.scrollHeight;
      }
      if (status.running) {
        scrapeTimer = setTimeout(poll, 500);
      } else if (status.done) {
        log.textContent += '\n--- 采集完成，刷新数据 ---\n';
        btn.disabled = false;
        btn.textContent = '采集';
        // Refresh data and switch to calendar view
        refreshAllData();
        switchView('calendar');
      } else {
        scrapeTimer = setTimeout(poll, 500);
      }
    } catch(e) {
      log.textContent += '轮询失败: ' + e.message + '\n';
      scrapeTimer = setTimeout(poll, 2000);
    }
  };
  poll();
}

function closeScrapePanel() {
  document.getElementById('scrapePanel').style.display = 'none';
  if (scrapeTimer) { clearTimeout(scrapeTimer); scrapeTimer = null; }
}

function showWhitelistHistory(name) {
  document.getElementById('modalTitle').textContent = name + ' - 历史节点';
  let body = document.getElementById('modalBody');
  body.innerHTML = '';
  let filtered = allEvents.filter(e => e.clean === name || e.game === name);
  if (filtered.length === 0) {
    body.innerHTML = '<div style="text-align:center;padding:20px;color:#999">暂无历史记录</div>';
  } else {
    filtered.sort((a,b) => a.date < b.date ? 1 : -1);
    for (const e of filtered) {
      let div = document.createElement('div');
      div.className = 'modal-item';
      div.innerHTML = '<div class="mi-date">' + esc(e.date) + ' <span style="float:right;font-size:11px;color:' + (STATUS_COLOR[e.status] || '#999') + '">[' + esc(e.status||'') + ']</span></div><div class="mi-info">' + esc(e.test_name) + ' | ' + esc(e.test_type) + ' | ' + esc(e.source) + '</div>';
      body.appendChild(div);
    }
  }
  document.getElementById('modalOverlay').classList.add('show');
}

function buildCard(e, mode) {
  const sc = STATUS_COLOR[e.status] || '#ccc';
  const sbg = STATUS_BG[e.status] || '#eee';
  const tc = {'公测':'#2e7d32','内测':'#c62828','封测':'#f9a825','新版本':'#1565c0','日常更新':'#546e7a','资料片':'#7b1fa2'};
  let h = '<div class="card" style="border-left:4px solid '+(tc[e.test_type]||'#ccc')+'">';
  h += '<div class="card-header"><span class="game-name" onclick="event.stopPropagation();showHistory(\''+esc(e.clean).replace(/'/g,"\\'")+'\',\''+esc(e.game).replace(/'/g,"\\'")+'\')">'+esc(e.game)+'</span>';
  h += '<span style="display:flex;gap:4px;align-items:center;flex-shrink:0"><span class="status-badge" style="background:'+sbg+';color:'+sc+';font-size:10px;padding:1px 7px;border-radius:8px;font-weight:600">'+esc(e.status||'')+'</span><span style="font-size:11px;color:#999">'+(e.scrape_date?'📅'+esc(e.scrape_date)+' ':'')+esc(e.source)+'</span></span></div>';
  h += '<div class="badges"><span class="badge type-'+esc(e.test_type)+'">'+esc(e.test_type)+'</span><span class="badge">'+esc(e.test_name)+'</span>';
  if (e.need_code==='是') h += '<span class="badge need-code">需激活码</span>';
  if (e.is_wiped==='是') h += '<span class="badge wiped">删档</span>';
  h += '</div><div class="meta">'+esc(e.rating)+' 评价 / '+esc(e.download)+' 下载</div>';
  if (e.log) h += '<div class="log">'+esc(e.log)+'</div>';
  if (e.url) h += '<a class="link" href="'+esc(e.url)+'" target="_blank" onclick="event.stopPropagation()">'+esc(e.link_label||'来源')+'</a>';
  if (e.links) {
    e.links.split(' ').filter(Boolean).forEach((u,i) => { h += '<a class="link" href="'+esc(u)+'" target="_blank" onclick="event.stopPropagation()">信源'+(i+1)+'</a>'; });
  }
  if (mode === 'review') {
    const statuses = ['正常','新增','待审','弃用'];
    const types = ['公测','内测','封测','新版本','资料片','日常更新'];
    const yn = ['是','否'];
    h += '<div class="se">';
    h += '<div class="se-row"><label>状态:</label><select onchange="trackChange('+e.id+',\'status\',this.value)" onclick="event.stopPropagation()">';
    statuses.forEach(s => { h += '<option value="'+s+'"'+(e.status===s?' selected':'')+'>'+s+'</option>'; });
    h += '</select><label>类型:</label><select onchange="trackChange('+e.id+',\'type\',this.value)" onclick="event.stopPropagation()">';
    types.forEach(t => { h += '<option value="'+t+'"'+(e.test_type===t?' selected':'')+'>'+t+'</option>'; });
    h += '</select><label>日期:</label><input type="date" value="'+esc(e.date)+'" class="fd" onchange="trackChange('+e.id+',\'test_time\',this.value)" onclick="event.stopPropagation()"></div>';
    h += '<div class="se-row"><label>激活码:</label><select onchange="trackChange('+e.id+',\'need_code\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.need_code===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select><label>删档:</label><select onchange="trackChange('+e.id+',\'is_wiped\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.is_wiped===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select><label>正式运营:</label><select onchange="trackChange('+e.id+',\'is_formal\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.is_formal===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select></div>';
      h += '<div style="margin-top:4px;display:flex;gap:6px;align-items:center"><span class="move-btn move-to-schedule" onclick="event.stopPropagation();moveToSchedule('+e.id+',\''+esc(e.clean)+'\')">移入测试表</span><span class="move-btn" style="background:#fce4ec;color:#c62828;border:1px solid #f8bbd0" onclick="event.stopPropagation();deleteEvent('+e.id+')">删除节点</span>';
      try{var _s=localStorage.getItem("mr_"+e.id);if(_s!==null)e.manual_reviewed=parseInt(_s)}catch(ex){}
    if (e.manual_reviewed) {
        h += '<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px;border:1px solid #ffcc02">人工已审核</span>';
      } else {
        h += '<label style="font-size:10px;color:#999;margin-left:4px"><input type="checkbox" onchange="trackChange('+e.id+',\'manual_reviewed\',this.checked?1:0);saveAll()" onclick="event.stopPropagation()"> 人工已审核</label>';
      }
      h += '</div>';
      h += '</div>';
  } else if (mode === 'schedule') {
    const statuses = ['正常','新增','待审','弃用'];
    const types = ['公测','内测','封测','新版本','资料片','日常更新'];
    const yn = ['是','否'];
    h += '<div class="se">';
    h += '<div class="se-row"><label>游戏名:</label><input type="text" value="'+esc(e.game)+'" class="se-input" onchange="trackChange('+e.id+',\'name\',this.value)" onclick="event.stopPropagation()">';
    h += '<label>测试名:</label><input type="text" value="'+esc(e.test_name)+'" class="se-input" onchange="trackChange('+e.id+',\'test_name\',this.value)" onclick="event.stopPropagation()">';
    h += '<label>状态:</label><select onchange="trackChange('+e.id+',\'status\',this.value)" onclick="event.stopPropagation()">';
    statuses.forEach(s => { h += '<option value="'+s+'"'+(e.status===s?' selected':'')+'>'+s+'</option>'; });
    h += '</select><label>类型:</label><select onchange="trackChange('+e.id+',\'type\',this.value)" onclick="event.stopPropagation()">';
    types.forEach(t => { h += '<option value="'+t+'"'+(e.test_type===t?' selected':'')+'>'+t+'</option>'; });
    h += '</select></div>';
    h += '<div class="se-row"><label>日期:</label><input type="date" value="'+esc(e.date)+'" class="fd" onchange="trackChange('+e.id+',\'test_time\',this.value)" onclick="event.stopPropagation()">';
    h += '<label>激活码:</label><select onchange="trackChange('+e.id+',\'need_code\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.need_code===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select><label>删档:</label><select onchange="trackChange('+e.id+',\'is_wiped\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.is_wiped===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select><label>正式运营:</label><select onchange="trackChange('+e.id+',\'is_formal\',this.value)" onclick="event.stopPropagation()">';
    yn.forEach(v => { h += '<option value="'+v+'"'+(e.is_formal===v?' selected':'')+'>'+v+'</option>'; });
    h += '</select></div>'; // close formal select and se-row
    h += '<div class="se-row" style="justify-content:flex-end;margin-top:4px;gap:6px">';
    if (scheduleSub === 'new') h += '<span class="move-btn move-to-schedule" onclick="event.stopPropagation();setTimeout(function(){trackChange('+e.id+',\'exported\',1);saveAll()},0)">移到已导出</span>';
    if (scheduleSub === 'exported') h += '<span class="move-btn move-to-review" onclick="event.stopPropagation();setTimeout(function(){trackChange('+e.id+',\'exported\',0);saveAll()},0)">移回新增</span>';
    h += '<span class="move-btn move-to-review" onclick="event.stopPropagation();if(confirm(\'确认移出测试表？\')){setTimeout(function(){trackChange('+e.id+',\'removed\',1);saveAll()},0)}">移除测试表</span>';
    h += '<span class="move-btn" style="background:#fce4ec;color:#c62828;border:1px solid #f8bbd0" onclick="event.stopPropagation();deleteEvent('+e.id+')">删除节点</span>';
    try{var _s=localStorage.getItem("mr_"+e.id);if(_s!==null)e.manual_reviewed=parseInt(_s)}catch(ex){}
    if (e.manual_reviewed) {
      h += '<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px;border:1px solid #ffcc02">人工已审核</span>';
    } else {
      h += '<label style="font-size:10px;color:#999;margin-left:4px"><input type="checkbox" onchange="trackChange('+e.id+',\'manual_reviewed\',this.checked?1:0);saveAll()" onclick="event.stopPropagation()"> 人工已审核</label>';
    }
    h += '</div>';
    h += '</div>';
  }
  h += '</div>';
  return h;
}

function render(filterGame) {
  const container = document.getElementById('container');
  container.innerHTML = '';
  let hasAny = false;

  for (const key of sortedKeys) {
    const cf = getCF(key);
    let fe = allDates[key].filter(e => {
      if (e.status === '弃用') return false;
      if (filterGame && !e.game.includes(filterGame) && !e.clean.includes(filterGame)) return false;
      if (cf.status.length && !cf.status.includes(e.status)) return false;
      if (cf.type.length && !cf.type.includes(e.test_type)) return false;
      if (cf.source.length && !cf.source.includes(e.source)) return false;
      return true;
    });
    if (!fe.length) continue;
    hasAny = true;

    const d = parseDate(key);
    const col = document.createElement('div');
    col.className = 'day-col';
    col.dataset.date = key;

    const header = document.createElement('div');
    header.className = 'day-header';
    const isToday = (key === fmtDate(new Date()));
    if (isToday) { header.style.background = 'linear-gradient(135deg,#667eea,#764ba2)'; header.style.color = '#fff'; }
    const filterActive = cf.status.length || cf.type.length || cf.source.length;
    header.innerHTML = `<span>${d.getMonth()+1}月${d.getDate()}日 <span class="weekday">周${weekdays[d.getDay()]}</span></span><span class="count">${fe.length}</span><span class="cf-toggle${filterActive?' active':''}" onclick="toggleColFilter(event,'${key}')">⚙</span>`;
    col.appendChild(header);

    // inline filter panel
    const fp = document.createElement('div');
    fp.className = 'col-filter-inline';
    fp.id = 'cfp-'+key;
    if (openFilterCols.has(key)) fp.classList.add('show');
    let fpHtml = '';
    ['status','type','source'].forEach(cat => {
      const label = {status:'状态',type:'类型',source:'来源'}[cat];
      fpHtml += '<div class="cfi-row"><span class="cfi-label">'+label+'</span>';
      FILTER_CHIPS[cat].forEach(v => {
        const active = cf[cat].includes(v);
        fpHtml += '<span class="cfi-chip'+(active?' active':'')+'" data-cat="'+cat+'" data-val="'+v+'" onclick="toggleChip(\''+key+'\',\''+cat+'\',\''+v+'\')">'+v+'</span>';
      });
      fpHtml += '</div>';
    });
    fpHtml += '<div style="display:flex;justify-content:space-between;margin-top:4px"><span class="cfi-close" onclick="clearColFilter(\''+key+'\')">清除筛选</span><span class="cfi-close" onclick="openFilterCols.delete(\''+key+'\');render(document.getElementById(\'searchInput\').value.trim())">收起</span></div>';
    fp.innerHTML = fpHtml;
    col.appendChild(fp);

    const body = document.createElement('div');
    const typeOrder = {'公测':0,'内测':1,'封测':2,'资料片':3,'新版本':4,'日常更新':5};
    const statusOrder = {'正常':0,'待审':1,'新增':2};
    for (const e of fe.sort((a,b)=>{
      if (a.manual_reviewed && !b.manual_reviewed) return -1;
      if (!a.manual_reviewed && b.manual_reviewed) return 1;
      const ta = typeOrder[a.test_type] ?? 99;
      const tb = typeOrder[b.test_type] ?? 99;
      if (ta !== tb) return ta - tb;
      const sa = statusOrder[a.status] ?? 99;
      const sb = statusOrder[b.status] ?? 99;
      if (sa !== sb) return sa - sb;
      return (a.test_name || '').localeCompare(b.test_name || '', 'zh-CN');
    })) {
      const typeColor = {'公测':'#2e7d32','内测':'#c62828','封测':'#f9a825','新版本':'#1565c0','日常更新':'#546e7a','资料片':'#7b1fa2'};
      const card = document.createElement('div');
      card.className = 'card';
      card.style.borderLeft = '4px solid ' + (typeColor[e.test_type] || '#ccc');
      card.onclick = () => showHistory(e.clean, e.game);
      card.innerHTML = `
        <div class="card-header">
          <span class="game-name" onclick="event.stopPropagation();showHistory('${e.clean.replace(/'/g,"\\'")}','${e.game.replace(/'/g,"\\'")}')">${esc(e.game)}</span>
          <span style="display:flex;gap:4px;align-items:center;flex-shrink:0">
            <span style="font-size:11px;color:#999">${e.scrape_date?'📅'+esc(e.scrape_date)+' ':''}${esc(e.source)}</span>
          </span>
        </div>
        <div class="badges">
          <span class="badge type-${esc(e.test_type)}">${esc(e.test_type)}</span>
          <span class="badge">${esc(e.test_name)}</span>
          ${e.need_code==='是'?'<span class="badge need-code">需激活码</span>':''}
          ${e.is_wiped==='是'?'<span class="badge wiped">删档</span>':''}
          ${e.status==='弃用'?'<span class="badge" style="background:#fce4ec;color:#c62828;font-size:10px">弃用</span>':''}
          ${(e.status!=='正常' && e.status!=='弃用' && e.status!=='新增' && e.status!=='待审') ? '<span class="badge" style="background:#f0f0f0;color:#888;font-size:10px">未入表</span>' : ''}
          ${((e.status==='新增'||e.status==='待审') && !inWhitelist(e.clean)) ? '<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px">待审核</span>' : ''}
        </div>
        <div class="meta">${esc(e.rating)} 评价 / ${esc(e.download)} 下载</div>
        ${e.log ? `<div class="log">${esc(e.log)}</div>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${e.url ? `<a class="link" href="${esc(e.url)}" target="_blank" onclick="event.stopPropagation()" style="display:inline;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px">${esc(e.link_label || '来源')}</a>` : ''}
          ${e.links ? e.links.split(' ').filter(Boolean).map((u, i) => `<a class="link" href="${esc(u)}" target="_blank" onclick="event.stopPropagation()" style="display:inline;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px">信源${i+1}</a>`).join('') : ''}
        </div>
        ${e.merged_source ? '<span class="badge" style="background:#e3f2fd;color:#1565c0;font-size:10px">'+esc(e.merged_source)+'</span>' : ''}
        ${e.manual_reviewed ? '<span class="badge" style="background:#fff3e0;color:#e65100;font-size:10px;border:1px solid #ffcc02">人工已审核</span>' : ''}
      `;
      body.appendChild(card);
    }
    col.appendChild(body);
    container.appendChild(col);
  }

  if (!hasAny) {
    container.innerHTML = '<div style="text-align:center;padding:40px;color:#999;white-space:normal">无匹配结果</div>';
    return;
  }

  // scroll to today
  const todayKey = fmtDate(new Date());
  const cols = container.querySelectorAll('.day-col');
  for (let i = 0; i < cols.length; i++) {
    if (cols[i].dataset.date === todayKey) {
      const scrollTo = cols[i].offsetLeft - (container.clientWidth - 380) / 2;
      container.scrollLeft = Math.max(0, scrollTo);
      break;
    }
  }
}

function showHistory(cleanName, displayName) {
  document.getElementById('modalTitle').textContent = displayName + ' - 历史节点';
  let body = document.getElementById('modalBody');
  body.innerHTML = '';
  let filtered = allEvents.filter(e => e.clean === cleanName);
  if (filtered.length === 0) {
    body.innerHTML = '<div style="text-align:center;padding:20px;color:#999">暂无历史记录</div>';
  } else {
    filtered.sort((a,b) => a.date < b.date ? 1 : -1);
    for (const e of filtered) {
      let div = document.createElement('div');
      div.className = 'modal-item';
      div.innerHTML = `
        <div class="mi-date">${esc(e.date)} <span style="float:right;font-size:11px;color:${STATUS_COLOR[e.status]||'#999'}">[${esc(e.status||'')}]</span></div>
      <div class="mi-info">${esc(e.test_name)} | ${esc(e.test_type)} | ${esc(e.source)}</div>
      <div style="margin-top:4px"><span class="move-btn" style="background:#fce4ec;color:#c62828;border:1px solid #f8bbd0;font-size:10px;padding:1px 6px;border-radius:4px;cursor:pointer" onclick="event.stopPropagation();deleteEvent(${e.id})">删除</span></div>
      `;
      body.appendChild(div);
    }
  }
  document.getElementById('modalOverlay').classList.add('show');
}
function closeModal() { document.getElementById('modalOverlay').classList.remove('show'); }
document.getElementById('modalOverlay').addEventListener('click', e => { if(e.target===e.currentTarget) closeModal(); });

// if API available, fetch latest whitelist + events
if (API_URL) {
  Promise.all([
    fetch(API_BASE + '/api/whitelist').then(r => r.json()).catch(() => null),
    fetch(API_BASE + '/api/events').then(r => r.json()).catch(() => null)
  ]).then(([wlData, fresh]) => {
    if (wlData && Array.isArray(wlData) && wlData.length) {
      WHITELIST.length = 0;
      wlData.forEach(n => WHITELIST.push(n));
    }
    if (fresh) {
      allEvents = fresh.map(e => ({
        id: e.id, game: e.display_name, clean: e.clean_name,
        test_name: e.test_name, date: e.test_time, test_type: e.test_type,
        need_code: e.need_code, is_wiped: e.is_wiped, is_formal: e.is_formal, exported: e.exported||0, removed: e.removed_from_schedule||0,
        rating: e.rating, download: e.download_count,
        links: e.tip_links, log: e.log_text,
        source: e.source, url: e.link,
        link_label: e.source, status: e.status || '新增', source_type: e.source_type, scrape_date: e.scrape_date
      }));
      allDates = {};
      for (const e of allEvents) {
        let d = parseDate(e.date);
        if (!d) continue;
        let key = fmtDate(d);
        if (!allDates[key]) allDates[key] = [];
        allDates[key].push(e);
      }
      sortedKeys = Object.keys(allDates).sort();
    }
    switchView('calendar');
  }).catch(() => switchView('calendar'));
} else {
  switchView('calendar');
}
</script>
</body>
</html>"""

    path = os.path.join(BASE_DIR, "calendar.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"日历已生成: {os.path.abspath(path)}")
    if not getattr(sys, 'frozen', False):
        webbrowser.open(os.path.abspath(path))


