"""数据库操作：保存、查询、URL清理"""

import os
import re
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.error

from database.schema import init_db, DB_PATH
from scraper.utils import normalize_date


def save_to_sqlite(df):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    for _, row in df.iterrows():
        clean_name = row.get("所属游戏(纯净)", "") or row.get("所属游戏", "")
        display_name = row.get("所属游戏", "")
        test_name = row.get("测试名称", "")
        test_time = normalize_date(row.get("测试时间", ""))
        test_type = row.get("测试类型", "")

        if not clean_name or not test_name or not test_time:
            continue

        conn.execute("""
            INSERT INTO games (clean_name, display_name, first_seen)
            VALUES (?, ?, ?)
            ON CONFLICT(clean_name) DO UPDATE SET display_name=excluded.display_name
        """, (clean_name, display_name, today))

        cur = conn.execute("SELECT id FROM games WHERE clean_name=?", (clean_name,))
        game_id = cur.fetchone()[0]

        dup = conn.execute(
            "SELECT id FROM events WHERE game_id=? AND test_time=? AND manual_edit=1",
            (game_id, test_time)
        ).fetchone()
        if dup:
            continue

        conn.execute("""
            INSERT INTO events (game_id, test_name, test_time, test_type,
                need_code, is_wiped, server_region, is_formal,
                rating, download_count, tip_links, latest_link, log_text,
                link, source, scrape_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, test_name, test_time) DO UPDATE SET
                test_type=excluded.test_type,
                need_code=excluded.need_code,
                is_wiped=excluded.is_wiped,
                server_region=excluded.server_region,
                is_formal=excluded.is_formal,
               rating=excluded.rating,
               download_count=excluded.download_count,
                scrape_date=excluded.scrape_date,
                tip_links=excluded.tip_links,
                latest_link=excluded.latest_link,
                log_text=excluded.log_text,
                link=excluded.link,
                source=excluded.source,
                scrape_date=excluded.scrape_date
        """, (
            game_id, test_name, test_time, test_type,
            row.get("需要激活码", ""), row.get("是否删档", ""),
            row.get("服务器地区", ""), row.get("是否正式运营", ""),
            row.get("评价数", ""), row.get("下载/预约数", ""),
            row.get("温馨提示链接", ""), row.get("最新动态链接", ""),
            row.get("日志原文", ""),
            row.get("链接", ""), row.get("来源", ""), today
        ))
    conn.commit()
    conn.close()


def query_game(name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT g.display_name, g.clean_name, e.test_name, e.test_time,
               e.test_type, e.need_code, e.is_wiped, e.server_region,
               e.is_formal, e.rating, e.download_count, e.source, e.scrape_date,
               rv.verdict as review_verdict, rv.confidence as review_confidence,
               rv.reasoning as review_reasoning, rv.review_date as review_date
        FROM events e JOIN games g ON e.game_id = g.id
        LEFT JOIN reviews rv ON e.id = rv.event_id
        WHERE g.clean_name LIKE ? OR g.display_name LIKE ?
        ORDER BY e.test_time DESC, e.scrape_date DESC
    """, (f"%{name}%", f"%{name}%"))
    rows = cur.fetchall()
    conn.close()
    return rows


def extract_urls(tip_links, max_count=5):
    if not tip_links:
        return ""
    raw = re.findall(r'https?://[^\s|]+', tip_links)
    cleaned = []
    seen = set()
    for u in raw:
        u = u.rstrip(".:,;")
        if not u or u in seen:
            continue
        seen.add(u)
        cleaned.append(u)
    if not cleaned:
        return ""
    accessible = filter_accessible_urls(cleaned)
    return " ".join(accessible[:max_count])


def filter_accessible_urls(urls, timeout=3):
    try:
        results = []
        def check(u):
            try:
                req = urllib.request.Request(u, method="HEAD")
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=timeout)
                return u if resp.status < 400 else None
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = {pool.submit(check, u): u for u in urls}
            for fut in as_completed(futs):
                r = fut.result()
                if r:
                    results.append(r)
        return results
    except Exception:
        return urls


def clean_tip_links():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, tip_links FROM events WHERE tip_links IS NOT NULL AND tip_links != ''"
    ).fetchall()
    total = len(rows)
    fixed = 0
    removed_total = 0
    for i, (eid, tip_links) in enumerate(rows, 1):
        urls = re.findall(r'https?://[^\s|]+', tip_links)
        if not urls:
            continue
        cleaned = []
        seen = set()
        for u in urls:
            u = u.rstrip(".:,;")
            if not u or u in seen:
                continue
            seen.add(u)
            cleaned.append(u)
        accessible = filter_accessible_urls(cleaned)
        kept = accessible[:5]
        before = len(urls)
        after = len(kept)
        if after < before:
            new_tip = " | ".join(kept) if kept else ""
            conn.execute("UPDATE events SET tip_links=? WHERE id=?", (new_tip, eid))
            fixed += 1
            removed_total += before - after
        if i % 50 == 0:
            conn.commit()
            print(f"  进度: {i}/{total}，已修复 {fixed} 条")
    conn.commit()
    conn.close()
    print(f"清理完成: 检查 {total} 条，修复 {fixed} 条，移除 {removed_total} 个失效链接")
