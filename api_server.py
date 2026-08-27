"""HTTP API 服务模块"""

import os
import json
import re
import sqlite3
import csv
import threading
import socketserver
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

from database.schema import DB_PATH, init_db
from merger import normalize_game_name
from scraper.utils import normalize_date, classify_source_by_url


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

METASO_TOKEN = os.environ.get("METASO_TOKEN", "")
METASO_URL = os.environ.get("METASO_URL", "http://localhost:8000")
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
AI_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
AI_BASE_URL = os.environ.get("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
AI_MODEL = os.environ.get("DASHSCOPE_MODEL", "deepseek-v4-flash")


# ==================== 采集日志捕获 ====================

_scrape_logs = []
_scrape_running = False
_scrape_done = False
_scrape_lock = threading.Lock()


def _log(msg):
    with _scrape_lock:
        _scrape_logs.append(msg)
    print(msg)


def _run_scrape():
    global _scrape_running, _scrape_done
    with _scrape_lock:
        _scrape_logs.clear()
        _scrape_running = True
        _scrape_done = False
    try:
        from config_manager import init_configs
        from scraper.taptap import scrape_taptap_reserve, scrape_taptap_in_app_event

        from scraper.utils import clean_download_count
        from merger import normalize_game_name
        import pandas as pd
        from database.operations import save_to_sqlite
        from html_generator.calendar import generate_calendar
        from html_generator.kanban import generate_kanban
        from html_generator.schedule import generate_test_schedule

        _log("=" * 40)
        _log("开始采集 TapTap 预约榜 + 新版本榜")
        _log("=" * 40)
        init_configs()
        init_db()

        cols = [
            "所属游戏", "所属游戏(纯净)", "测试名称", "测试时间", "测试类型",
            "需要激活码", "是否删档", "服务器地区", "是否正式运营",
            "评价数", "下载/预约数", "温馨提示链接", "最新动态链接", "日志原文", "链接", "来源"
        ]
        all_data = []
        _log("[1/2] 采集 TapTap 预约榜...")
        all_data.extend(scrape_taptap_reserve())
        _log(f"  TapTap 预约榜完成: {len(all_data)} 条")

        _log("[2/2] 采集 TapTap 新版本榜...")
        all_data.extend(scrape_taptap_in_app_event())
        _log(f"  TapTap 新版本榜完成: {len(all_data)} 条")

        if all_data:
            df = pd.DataFrame(all_data)
            df['下载/预约数'] = df['下载/预约数'].apply(clean_download_count)
            df['所属游戏(纯净)'] = df['所属游戏'].apply(normalize_game_name)
            from merger import merge_duplicates
            df = merge_duplicates(df)
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            df = df[cols]
            save_to_sqlite(df)
            _log(f"已保存 {len(df)} 条记录到数据库")

        _log("导入公众号数据...")
        from public_account import import_all_public_account_sheets
        import_all_public_account_sheets()
        _log("合并公众号数据...")
        from merger import merge_sources
        merge_sources()
        _log("重新生成看板...")
        generate_calendar(api_url="http://127.0.0.1:8765")
        generate_kanban(api_url="http://127.0.0.1:8765")
        generate_test_schedule()
        _log("采集完成！看板已更新")
    except Exception as e:
        _log(f"采集出错: {e}")
        import traceback
        _log(traceback.format_exc())
    finally:
        with _scrape_lock:
            _scrape_running = False
            _scrape_done = True


def get_scrape_status():
    with _scrape_lock:
        return {"running": _scrape_running, "done": _scrape_done, "logs": list(_scrape_logs)}


def start_scrape():
    global _scrape_running
    with _scrape_lock:
        if _scrape_running:
            return False
    t = threading.Thread(target=_run_scrape, daemon=True)
    t.start()
    return True


# ==================== 搜索与审查 ====================

def search_web(q, t=15):
    import requests as _
    import json as _j
    try:
        j = _.post(METASO_URL + '/v1/chat/completions',
                   json={'model': 'concise', 'messages': [{'role': 'user', 'content': q}],
                         'stream': False},
                   headers={'Authorization': 'Bearer ' + METASO_TOKEN, 'Content-Type': 'application/json'},
                   timeout=t).json()
        return j['choices'][0]['message']['content'] if 'choices' in j else ''
    except Exception:
        return ''


def extract_v(t):
    import json as _j
    try:
        s = t.index('{')
        e = t.rindex('}') + 1
        return _j.loads(t[s:e])
    except Exception:
        return {'verdict': 'unverified', 'confidence': 'no_source', 'reasoning': 'parse failed'}


def review_event(eid):
    import sqlite3, json, requests as _, datetime as d
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute('''SELECT e.*,g.display_name FROM events e JOIN games g ON e.game_id=g.id WHERE e.id=?''', (eid,)).fetchone()
    if not row:
        conn.close()
        return {'error': 'not found'}
    gn = row['display_name'] or ''
    tn = row['test_name'] or ''
    tt = row['test_type'] or ''
    td = row['test_time'] or ''
    conn.close()
    sr = search_web(gn + ' ' + tn + ' ' + td)
    if not sr:
        v = {'verdict': 'unverified', 'confidence': 'no_source', 'reasoning': 'empty'}
    else:
        p = '根据搜索结果判断游戏节点是否属实。\n\n游戏：' + gn + '\n节点：' + tn + '\n类型：' + tt + '\n日期：' + td + '\n\n搜索结果：\n' + sr[:800] + '\n\nJSON：{"verdict":"confirmed/contradicted/unverified","confidence":"official/media_consensus/single_source/no_source","reasoning":"依据"}'
        try:
            j = _.post('https://api.deepseek.com/chat/completions',
                       headers={'Authorization': 'Bearer ' + DS_KEY, 'Content-Type': 'application/json'},
                       json={'model': DS_MODEL, 'messages': [{'role': 'user', 'content': p}],
                             'max_tokens': 300, 'temperature': 0.1},
                       timeout=30).json()
            rv = j['choices'][0]['message']['content'] if 'choices' in j else '{}'
            v = extract_v(rv)
        except Exception as e:
            v = {'verdict': 'unverified', 'confidence': 'no_source', 'reasoning': 'API err: ' + str(e)}
    today = d.datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO reviews (event_id,review_date,verdict,confidence,reasoning,sources) VALUES (?,?,?,?,?,?)",
        (eid, today, v.get('verdict', 'unverified'), v.get('confidence', 'no_source'), v.get('reasoning', ''),
         json.dumps(v.get('sources', []), ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {'event_id': eid, 'verdict': v.get('verdict', 'unverified'), 'confidence': v.get('confidence', 'no_source'),
            'reasoning': v.get('reasoning', '')[:100]}


# ==================== API 服务 ====================

def start_api_server(port=8765, db_path=None):
    """启动本地 HTTP API，供看板实时更新状态"""
    import socketserver
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import json as json_mod
    import threading as _thr
    _db_lock = _thr.Lock()

    class ThreadingAPIHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True

    _DB = db_path or DB_PATH
    with sqlite3.connect(_DB, timeout=10) as _wal_conn:
        _wal_conn.execute("PRAGMA journal_mode=WAL")
        _wal_conn.execute("PRAGMA busy_timeout=10000")

    class APIHandler(BaseHTTPRequestHandler):
        def handle_error(self, exc=None):
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": False, "error": str(exc) if exc else "内部错误"}).encode("utf-8"))
            except Exception:
                pass

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            if self.path == "/api/debug":
                import json as _j
                _db_info = {
                    "DB_PATH": str(_DB),
                    "BASE_DIR": str(BASE_DIR),
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(_j.dumps(_db_info).encode("utf-8"))
                return
            if self.path == "/api/events":
                conn = sqlite3.connect(_DB, timeout=10)
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
                rows = []
                for r in cur.fetchall():
                    d = dict(r)
                    if not d.get("status"):
                        d["status"] = "新增"
                    rows.append(d)
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps(rows, ensure_ascii=False).encode("utf-8"))
                return

            elif self.path == "/api/whitelist":
                wl_path = os.path.join(BASE_DIR, "game_whitelist.txt")
                mapping_path = os.path.join(BASE_DIR, "complete_game_mapping.csv")
                code_map = {}
                if os.path.exists(mapping_path):
                    with open(mapping_path, "r", encoding="utf-8-sig") as f:
                        for row in csv.DictReader(f):
                            nm = normalize_game_name(row.get("Name", ""))
                            cd = row.get("GameCode", "").strip()
                            if nm and cd: code_map[nm] = cd
                entries = []
                if os.path.exists(wl_path):
                    with open(wl_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line: continue
                            parts = line.split("|")
                            raw_name = parts[0].strip()
                            name = normalize_game_name(raw_name)
                            eid = parts[1].strip() if len(parts) > 1 else code_map.get(name, "")
                            if name:
                                entries.append({"name": name, "id": eid})
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps(entries, ensure_ascii=False).encode("utf-8"))
            elif self.path in ("/", "/calendar.html"):
                cal_path = os.path.join(BASE_DIR, "calendar.html")
                if os.path.exists(cal_path):
                    with open(cal_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
            elif self.path == "/kanban.html":
                k_path = os.path.join(BASE_DIR, "kanban.html")
                if os.path.exists(k_path):
                    with open(k_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
            elif self.path == "/test_schedule.html":
                ts_path = os.path.join(BASE_DIR, "test_schedule.html")
                if os.path.exists(ts_path):
                    with open(ts_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
            elif self.path == "/review_candidates.html":
                rc_path = os.path.join(BASE_DIR, "review_candidates.html")
                if os.path.exists(rc_path):
                    with open(rc_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
            elif self.path == "/view.html":
                v_path = os.path.join(BASE_DIR, "view.html")
                if os.path.exists(v_path):
                    with open(v_path, "rb") as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
            elif self.path == "/api/settings":
                settings = {}
                for fname in ("config_taptap_hot.json", "config_taptap_reserve.json", "config_haoyou.json", "settings.json"):
                    fpath = os.path.join(BASE_DIR, "config", fname)
                    if os.path.exists(fpath):
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                settings[fname] = json_mod.load(f)
                        except Exception:
                            settings[fname] = {}
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps(settings, ensure_ascii=False).encode("utf-8"))
            elif self.path == "/api/scrape_status":
                status = get_scrape_status()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps(status, ensure_ascii=False).encode("utf-8"))
            else:
                self.send_response(404)
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "")
                if self.path == "/api/upload-public-account" and "multipart" in content_type:
                    import traceback as _tb_up
                    try:
                        import email
                        _msg = email.message_from_bytes(b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + body)
                        _filename = None
                        _filedata = None
                        if _msg.is_multipart():
                            for _part in _msg.walk():
                                if _part.get_content_maintype() == 'multipart':
                                    continue
                                _fn = _part.get_filename()
                                if _fn:
                                    _filename = _fn
                                    _filedata = _part.get_payload(decode=True)
                                    break
                        if not _filedata or not _filename:
                            raise ValueError("未找到上传文件")
                        _save_dir = os.path.join(BASE_DIR, "公众号数据")
                        if not os.path.isdir(_save_dir):
                            os.makedirs(_save_dir)
                        _save_path = os.path.join(_save_dir, _filename)
                        with open(_save_path, "wb") as _f:
                            _f.write(_filedata)
                        from public_account import import_public_account_sheet
                        from merger import merge_sources
                        from html_generator.calendar import generate_calendar
                        from html_generator.kanban import generate_kanban
                        _count = import_public_account_sheet(_save_path)
                        merge_sources()
                        try:
                            generate_calendar(api_url=f"http://127.0.0.1:{port}")
                        except Exception:
                            pass
                        try:
                            generate_kanban(api_url=f"http://127.0.0.1:{port}")
                        except Exception:
                            pass
                        try:
                            from html_generator.schedule import generate_test_schedule
                            generate_test_schedule()
                        except Exception:
                            pass
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                        self.end_headers()
                        self.wfile.write(json_mod.dumps({"ok": True, "count": _count}).encode("utf-8"))
                        return
                    except Exception as _e_up:
                        _tb_up.print_exc()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                        self.end_headers()
                        self.wfile.write(json_mod.dumps({"ok": False, "error": f"上传解析失败: {_e_up}"}).encode("utf-8"))
                        return
                data = json_mod.loads(body) if body and body.strip() else {}
            except Exception:
                import traceback as _tb_out
                _tb_out.print_exc()
                data = {}

            if self.path == "/api/update_status":
                event_id = data.get("id")
                new_status = data.get("status")
                if not event_id or new_status not in ("正常", "新增", "待审", "弃用"):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": "参数错误"}).encode("utf-8"))
                    return
                try:
                    conn = sqlite3.connect(_DB, timeout=10)
                    conn.execute("UPDATE events SET status=? WHERE id=?", (new_status, event_id))
                    conn.commit()
                    conn.close()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": True}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
            elif self.path == "/api/batch_update":
                try:
                    items = data if isinstance(data, list) else data.get("items") if isinstance(data, dict) else []
                    if not isinstance(items, list):
                        items = []
                    conn = sqlite3.connect(_DB, timeout=10)
                    for item in items:
                        eid = item.get("id")
                        st = item.get("status")
                        tp = item.get("type")
                        nm = item.get("name")
                        tn = item.get("test_name")
                        dt = item.get("test_time")
                        nc = item.get("need_code")
                        iw = item.get("is_wiped")
                        ifm = item.get("is_formal")
                        ex = item.get("exported")
                        rm = item.get("removed")
                        if eid:
                            updates = []
                            params = []
                            if st and st in ("正常", "新增", "待审", "弃用"):
                                updates.append("status=?")
                                params.append(st)
                            if tp and tp in ("公测", "内测", "封测", "新版本", "资料片", "日常更新"):
                                updates.append("test_type=?")
                                params.append(tp)
                            if tn is not None:
                                updates.append("test_name=?")
                                params.append(tn)
                            if dt:
                                updates.append("test_time=?")
                                params.append(dt)
                            if nc in ("是", "否"):
                                updates.append("need_code=?")
                                params.append(nc)
                            if iw in ("是", "否"):
                                updates.append("is_wiped=?")
                                params.append(iw)
                            if ifm in ("是", "否"):
                                updates.append("is_formal=?")
                                params.append(ifm)
                            if ex in (0, 1):
                                updates.append("exported=?")
                                params.append(ex)
                            if rm in (0, 1):
                                updates.append("removed_from_schedule=?")
                                params.append(rm)
                            if item.get("manual_reviewed") in (0, 1):
                                updates.append("manual_reviewed=?")
                                params.append(item.get("manual_reviewed"))
                            if updates:
                                updates.append("manual_edit=1")
                                params.append(eid)
                                conn.execute("UPDATE events SET " + ",".join(updates) + " WHERE id=?", params)
                            if nm:
                                row = conn.execute("SELECT game_id FROM events WHERE id=?", (eid,)).fetchone()
                                if row:
                                    old_gid = row[0]
                                    new_clean = normalize_game_name(nm)
                                    existing = conn.execute("SELECT id FROM games WHERE clean_name=? AND id!=?", (new_clean, old_gid)).fetchone()
                                    if existing:
                                        conn.execute("UPDATE events SET game_id=? WHERE game_id=?", (existing[0], old_gid))
                                        conn.execute("UPDATE games SET display_name=? WHERE id=?", (nm, existing[0]))
                                        remaining = conn.execute("SELECT COUNT(*) FROM events WHERE game_id=?", (old_gid,)).fetchone()[0]
                                        if remaining == 0:
                                            conn.execute("DELETE FROM games WHERE id=?", (old_gid,))
                                    else:
                                        conn.execute("UPDATE games SET display_name=?, clean_name=? WHERE id=?", (nm, new_clean, old_gid))
                                conn.execute("UPDATE events SET manual_edit=1 WHERE id=?", (eid,))
                    conn.commit()
                    conn.close()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": True, "count": len(items)}).encode("utf-8"))
                except Exception as e:
                    try: conn.close()
                    except: pass
                    err_msg = str(e)
                    if isinstance(e, sqlite3.IntegrityError) and "UNIQUE constraint" in err_msg:
                        err_msg = "该游戏在同一天已存在同名节点，请使用不同的名称"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": err_msg}).encode("utf-8"))
            elif self.path == "/api/delete_event":
                eid = data.get("id") if isinstance(data, dict) else None
                if eid:
                    conn = sqlite3.connect(_DB, timeout=10)
                    row = conn.execute("SELECT game_id FROM events WHERE id=?", (eid,)).fetchone()
                    if row:
                        game_id = row[0]
                        conn.execute("DELETE FROM events WHERE id=?", (eid,))
                        remaining = conn.execute("SELECT COUNT(*) FROM events WHERE game_id=?", (game_id,)).fetchone()[0]
                        if remaining == 0:
                            conn.execute("DELETE FROM games WHERE id=?", (game_id,))
                    conn.commit()
                    conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": True}).encode("utf-8"))
            elif self.path == "/api/whitelist":
                games = data.get("games", []) if isinstance(data, dict) else []
                if not games:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": "empty whitelist"}).encode("utf-8"))
                    return
                wl_path = os.path.join(BASE_DIR, "game_whitelist.txt")
                tmp_path = wl_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    for entry in games:
                        name = entry.get("name", "") if isinstance(entry, dict) else entry
                        eid = entry.get("id", "") if isinstance(entry, dict) else ""
                        if name.strip():
                            f.write(name.strip() + ("|" + eid.strip() if eid else "") + "\n")
                os.replace(tmp_path, wl_path)
                conn = sqlite3.connect(_DB, timeout=10)
                for entry in games:
                    clean = normalize_game_name(entry.get("name", "").strip()) if isinstance(entry, dict) else normalize_game_name(entry.strip())
                    if clean:
                        conn.execute("""
                            UPDATE events SET status='正常', manual_edit=1
                            WHERE status IN ('新增','待审')
                            AND game_id IN (SELECT id FROM games WHERE clean_name LIKE ? OR ? LIKE '%'||clean_name||'%')
                        """, (f'%{clean}%', clean))
                updated = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": True, "count": len(games), "updated": updated}).encode("utf-8"))
            elif self.path == "/api/review_range":
                try:
                    start_date = data.get("start_date", "")
                    end_date = data.get("end_date", "")
                    if not start_date or not end_date:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                        self.end_headers()
                        self.wfile.write(json_mod.dumps({"ok": False, "error": "请选择日期"}).encode("utf-8"))
                        return
                    conn = sqlite3.connect(_DB, timeout=10)
                    conn.row_factory = sqlite3.Row
                    cur = conn.execute("""
                        SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
                               e.source, rv.verdict as review_verdict, rv.confidence as review_confidence,
                               rv.reasoning as review_reasoning, rv.review_date as review_date
                        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
                        WHERE e.test_time >= ? AND e.test_time <= ?
                        ORDER BY e.test_time ASC
                    """, (start_date, end_date))
                    rows = cur.fetchall()
                    need_review = [r for r in rows if not r["review_verdict"] or r["review_verdict"] == "pending"]
                    existing = [r for r in rows if r["review_verdict"] and r["review_verdict"] != "pending"]
                    results = []
                    for r in existing:
                        results.append({
                            "id": r["id"], "game": r["display_name"] or r["clean_name"],
                            "test_name": r["test_name"], "date": r["test_time"],
                            "test_type": r["test_type"], "source": r["source"] or "",
                            "verdict": r["review_verdict"], "confidence": r["review_confidence"] or "",
                            "reasoning": r["review_reasoning"] or "",
                        })
                    if need_review:
                        from openai import OpenAI as _RV_OA
                        import datetime as _RV_DT, json as _RV_J
                        _rv_client = _RV_OA(api_key=AI_API_KEY, base_url=AI_BASE_URL)
                        from collections import defaultdict as _DD
                        _groups = _DD(list)
                        for r in need_review:
                            _groups[(r["test_name"], r["test_time"])].append(r)
                        for key, group in _groups.items():
                            r = group[0]
                            eid = r["id"]
                            game_name = r["display_name"] or r["clean_name"]
                            test_name = r["test_name"]
                            test_time = r["test_time"]
                            test_type = r["test_type"]
                            source = r["source"] or ""
                            prompt = f"""请搜索并验证以下游戏节点是否真实可靠。
游戏名称：{game_name}
测试名称：{test_name}
测试时间：{test_time}
测试类型：{test_type}
来源：{source}

请按以下JSON格式回复（不要包含其他内容）：
{{"verdict": "confirmed", "confidence": "高|中|低", "reasoning": "分析说明"}}

verdict: confirmed(确认) 有官方公告或多方媒体确认
         contradicted(矛盾) 找到矛盾信息
         unverified(无法验证) 搜不到可靠佐证"""
                            try:
                                resp = _rv_client.chat.completions.create(
                                    model=AI_MODEL,
                                    messages=[{"role": "user", "content": prompt}],
                                    max_tokens=1024, temperature=0.1,
                                    extra_body={"enable_search": True, "search_options": {"forced_search": True, "search_strategy": "max"}}
                                )
                                reply = resp.choices[0].message.content.strip()
                                reply = reply.replace("```json", "").replace("```", "").strip()
                                parsed = _RV_J.loads(reply)
                                verdict = parsed.get("verdict", "unverified")
                                confidence = parsed.get("confidence", "低")
                                reasoning = parsed.get("reasoning", "")
                            except Exception as _rv_e:
                                verdict = "unverified"
                                confidence = "低"
                                reasoning = f"审查异常: {str(_rv_e)}"
                            today_str = _RV_DT.datetime.now().strftime("%Y-%m-%d %H:%M")
                            conn2 = sqlite3.connect(_DB, timeout=10)
                            for dup in group:
                                conn2.execute("""
                                    INSERT INTO reviews (event_id, review_date, verdict, confidence, reasoning, sources)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(event_id) DO UPDATE SET
                                        review_date=excluded.review_date, verdict=excluded.verdict,
                                        confidence=excluded.confidence, reasoning=excluded.reasoning
                                """, (dup["id"], today_str, verdict, confidence, reasoning, ""))
                            conn2.commit()
                            conn2.close()
                            for dup in group:
                                dup_name = dup["display_name"] or dup["clean_name"]
                                print(f"[AI审查已完成] {dup_name} - {test_name}: {verdict}")
                                results.append({
                                    "id": dup["id"], "game": dup_name,
                                    "test_name": test_name, "date": test_time,
                                    "test_type": test_type, "source": dup["source"] or "",
                                    "verdict": verdict, "confidence": confidence, "reasoning": reasoning,
                                })
                    conn.close()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": True, "results": results}).encode("utf-8"))
                except Exception as e:
                    import traceback as _tb
                    _tb.print_exc()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
            elif self.path == "/api/events/add":
                game_name = (data.get("game_name") or "").strip()
                test_name = (data.get("test_name") or "").strip()
                test_time = (data.get("test_time") or "").strip()
                test_type = data.get("test_type") or "内测"
                need_code = data.get("need_code")
                is_wiped = data.get("is_wiped")
                link = (data.get("link") or "").strip()
                if not game_name or not test_name or not test_time:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": "请填写完整信息"}).encode("utf-8"))
                    return
                try:
                    conn = sqlite3.connect(_DB, timeout=10)
                    clean_name = normalize_game_name(game_name)
                    today = datetime.now().strftime("%Y-%m-%d")
                    conn.execute("""
                        INSERT INTO games (clean_name, display_name, first_seen)
                        VALUES (?, ?, ?)
                        ON CONFLICT(clean_name) DO UPDATE SET display_name=excluded.display_name
                    """, (clean_name, game_name, today))
                    cur = conn.execute("SELECT id FROM games WHERE clean_name=?", (clean_name,))
                    game_id = cur.fetchone()[0]
                    conn.execute("""
                        INSERT INTO events (game_id, test_name, test_time, test_type,
                            need_code, is_wiped, link, source, scrape_date, status, source_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (game_id, test_name, test_time, test_type,
                          need_code, is_wiped, link, "手动", today, "新增", "manual"))
                    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.commit()
                    conn.close()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": True, "event_id": new_id}).encode("utf-8"))
                except Exception as e:
                    try: conn.close()
                    except: pass
                    err_msg = str(e)
                    if "UNIQUE constraint" in err_msg:
                        err_msg = "该游戏在同一天已存在同名节点"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                    self.end_headers()
                    self.wfile.write(json_mod.dumps({"ok": False, "error": err_msg}).encode("utf-8"))
            elif self.path == "/api/settings":
                for fname in ("config_taptap_hot.json", "config_taptap_reserve.json", "config_haoyou.json", "settings.json"):
                    fpath = os.path.join(BASE_DIR, "config", fname)
                    if fname in data and os.path.exists(fpath):
                        try:
                            with open(fpath, "w", encoding="utf-8") as f:
                                json_mod.dump(data[fname], f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": True}).encode("utf-8"))
            elif self.path == "/api/scrape":
                ok = start_scrape()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": ok}).encode("utf-8"))
            elif self.path == "/api/import-public-account":
                from public_account import import_all_public_account_sheets
                from merger import merge_sources
                count = import_all_public_account_sheets()
                merge_sources()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": True, "count": count}).encode("utf-8"))
            elif self.path.startswith("/api/export_events"):
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                start_date = qs.get("start", [""])[0]
                end_date = qs.get("end", [""])[0]
                conn = sqlite3.connect(_DB, timeout=10)
                conn.row_factory = sqlite3.Row
                query = "SELECT e.*, g.display_name, g.clean_name FROM events e JOIN games g ON e.game_id=g.id"
                params = []
                if start_date and end_date:
                    query += " WHERE e.test_time >= ? AND e.test_time <= ?"
                    params = [start_date, end_date]
                query += " ORDER BY e.test_time DESC"
                cur = conn.execute(query, params)
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps(rows, ensure_ascii=False).encode("utf-8"))
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "") or "*")
                self.end_headers()
                self.wfile.write(json_mod.dumps({"ok": False, "error": "not found"}).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    server = ThreadingAPIHTTPServer(("0.0.0.0", port), APIHandler)
    print(f"API 服务运行在 http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
