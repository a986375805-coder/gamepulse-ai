"""数据合并与去重模块"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from database.schema import DB_PATH
from scraper.utils import normalize_date, classify_source_by_url


def normalize_game_name(name):
    if not isinstance(name, str):
        return ""
    name_orig = name
    name = name.strip()
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[（(](?:官服|正版|手机版|安卓版|国服|国际服|手游版|移动版|测试|预约|删档|内测|公测|[\d.]+版本?|S\d)[^）)]*[）)]', '', name)
    suffixes = [
        r'官服$', r'正版$', r'手机版$', r'安卓版$', r'国服$', r'国际服$', r'手游版$', r'移动版$',
        r'-\d+月\d+日(?:上线)?$', r'-\d+月上线$', r'-\d+\.\d+版本$',
        r'-S\d+[^\-]*$', r'-[^\-]{2,10}联动$', r'-世界杯版本$', r'-新版本(?:预约)?$',
        r'-新赛季预约$', r'-重生日$', r'-次世代$', r'-悬疑剧情$', r'-中式民俗解谜$',
        r'-正版移植手游$', r'-1v4对抗$', r'-燃夏时速$', r'-中国都市开放世界$',
        r'-移动版$', r'-\w{2,6}测试$',
    ]
    for suf in suffixes:
        name = re.sub(suf, '', name, flags=re.IGNORECASE)
    name = re.sub(r'[—\-]\s*$', '', name)
    name = name.strip()
    return name if name else name_orig


def normalize_test_name(name):
    if not isinstance(name, str):
        return "其他"
    name = name.strip()
    if re.match(r'^(首发|正式上线|不删档上线|上线|首发上线|全平台上线|正式开服|不删档开服)$', name):
        return "首发/上线"
    if re.match(r'^(公测|公开测试|全平台公测|公测预约|不删档公测)$', name):
        return "公测"
    if re.match(r'^(内测|删档内测|不删档内测|限量内测|付费内测|计费删档|限号内测|计费测试|付费测试|安卓内测|iOS内测)$', name):
        return "内测"
    if re.match(r'^(新版本|版本更新|日常更新|日常维护|内容更新|版本预告)$', name):
        return "版本更新"
    if re.match(r'^(资料片|资料片预约|新资料片)$', name):
        return "资料片"
    if re.match(r'.*测试$', name):
        return "测试"
    return name


def merge_duplicates(df):
    df['标准化游戏'] = df['所属游戏'].apply(normalize_game_name)
    df['测试名称键'] = df['测试名称'].apply(normalize_test_name)
    group_cols = ['标准化游戏', '测试名称键', '测试时间']
    merged_rows = []
    for _, group in df.groupby(group_cols):
        first = group.iloc[0].to_dict()
        if len(group) > 1:
            first['来源'] = '+'.join(group['来源'].unique())
            links = group['链接'].dropna()
            first['链接'] = links.iloc[0] if len(links) > 0 else ''
            for col in ['评价数', '下载/预约数']:
                valid = group[col].dropna()
                valid = valid[valid != '']
                if len(valid) > 0:
                    first[col] = valid.iloc[0]
            test_names = group['测试名称'].dropna().unique()
            if len(test_names) > 1:
                first['测试名称'] = max(test_names, key=len)
            for col in ['需要激活码', '是否删档', '是否正式运营', '服务器地区', '测试类型']:
                if pd.isna(first.get(col)) or first.get(col) == '':
                    non_empty = group[col].dropna()
                    if len(non_empty) > 0:
                        first[col] = non_empty.iloc[0]
        first.pop('测试名称键', None)
        merged_rows.append(pd.Series(first))
    merged_df = pd.DataFrame(merged_rows)
    merged_df = merged_df.drop(columns=['标准化游戏'])
    merged_df['测试时间_排序'] = pd.to_datetime(merged_df['测试时间'], errors='coerce')
    merged_df = merged_df.sort_values('测试时间_排序', ascending=False).drop(columns='测试时间_排序')
    return merged_df


def merge_sources():
    """合并规则：正常/新增/待审 自动分类"""
    conn = sqlite3.connect(DB_PATH)

    # 清理: 合并因换行/多余空格导致重复的 game 记录
    games = conn.execute("SELECT id, clean_name FROM games").fetchall()
    norm_map = {}
    for gid, cname in games:
        key = re.sub(r'\s+', ' ', cname).strip()
        norm_map.setdefault(key, []).append((gid, cname))
    for norm_name, group in norm_map.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x[0])
        keep_id = group[0][0]
        for dup_id, _ in group[1:]:
            conn.execute("UPDATE events SET game_id=? WHERE game_id=?", (keep_id, dup_id))
            conn.execute("DELETE FROM games WHERE id=?", (dup_id,))
            print(f"  合并游戏 [{norm_name}]: id {dup_id} → {keep_id}")
        conn.execute("UPDATE games SET clean_name=? WHERE id=?", (norm_name, keep_id))

    # 根据链接重新分类来源
    for row in conn.execute("SELECT id, link, source, source_type FROM events"):
        new_source = classify_source_by_url(row[1])
        if new_source and new_source != row[2]:
            conn.execute("UPDATE events SET source=? WHERE id=?", (new_source, row[0]))

    # 获取所有爬取记录
    scrape_rows = conn.execute("""
        SELECT e.id, g.clean_name, e.test_type, e.test_time
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        WHERE e.source_type = 'scrape'
    """).fetchall()

    # 获取所有公众号记录
    pa_rows = conn.execute("""
        SELECT e.id, g.clean_name, e.test_type, e.test_time
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        WHERE e.source_type = 'public_account'
    """).fetchall()

    pa_lookup = {}
    for r in pa_rows:
        key = (r[1], r[2], r[3])
        pa_lookup[key] = r[0]

    scrape_lookup = {}
    for r in scrape_rows:
        key = (r[1], r[2], r[3])
        scrape_lookup[key] = r[0]

    # 规则1: 同名+同测试类型+同时间 在两者中都存在 → 待审
    matched_scrape = set()
    matched_pa = set()
    for key, sid in scrape_lookup.items():
        if key in pa_lookup:
            matched_scrape.add(sid)
            matched_pa.add(pa_lookup[key])

    if matched_scrape:
        conn.execute(
            "UPDATE events SET status='待审' WHERE id IN ({}) AND (status IS NULL OR status = '新增')".format(
                ",".join(str(x) for x in matched_scrape)
            )
        )
        cnt = conn.execute("SELECT changes()").fetchone()[0]
        if cnt: print(f"  待审: {cnt} 条（双方匹配）")
        conn.execute(
            "UPDATE events SET status='待审' WHERE id IN ({}) AND (status IS NULL OR status = '新增')".format(
                ",".join(str(x) for x in matched_pa)
            )
        )
        cnt = conn.execute("SELECT changes()").fetchone()[0]
        if cnt: print(f"  待审: {cnt} 条（公众号匹配）")

    # 规则2: 爬取有但公众号没有 → 新增
    new_ids = set(scrape_lookup.values()) - matched_scrape
    if new_ids:
        conn.execute(
            "UPDATE events SET status='新增' WHERE id IN ({}) AND (status IS NULL OR status = '')".format(
                ",".join(str(x) for x in new_ids)
            )
        )
        print(f"  新增: {len(new_ids)} 条（仅爬取）")

    # 规则3: 公众号有但爬取没有，且状态不是正常/弃用 → 待审
    pending_ids = set(pa_lookup.values()) - matched_pa
    if pending_ids:
        conn.execute(
            "UPDATE events SET status='待审' WHERE id IN ({}) AND status NOT IN ('正常','弃用')".format(
                ",".join(str(x) for x in pending_ids)
            )
        )
        print(f"  待审: {len(pending_ids)} 条（仅公众号，需人工审核）")

    # 自动将前天之前爬取的未导出节点标记为已导出
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    old_new = conn.execute(
        "UPDATE events SET exported=1, status='正常' WHERE status='新增' AND scrape_date < ?",
        (cutoff,)
    )
    if old_new.rowcount:
        print(f"  自动导出(新增→正常): {old_new.rowcount} 条（爬取时间早于 {cutoff}）")
    old_marked = conn.execute(
        "UPDATE events SET exported=1 WHERE (exported IS NULL OR exported=0) AND status!='新增' AND scrape_date < ?",
        (cutoff,)
    )
    if old_marked.rowcount:
        print(f"  自动导出(其他→已导出): {old_marked.rowcount} 条（爬取时间早于 {cutoff}）")

    # 规则4: 同名+同时间去重
    dup_rows = conn.execute("""
        SELECT e.id, g.clean_name, e.test_time, e.status
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
    """).fetchall()
    dup_groups = {}
    for r in dup_rows:
        nd = normalize_date(r[2])
        if not nd: continue
        key = (r[1], nd)
        dup_groups.setdefault(key, []).append((r[0], r[3]))
    priority = {'正常': 0, '待审': 1, '新增': 2, '弃用': 3}
    del_ids = []
    for key, group in dup_groups.items():
        if len(group) < 2: continue
        group.sort(key=lambda x: priority.get(x[1], 99))
        for rid, _ in group[1:]:
            del_ids.append(rid)
    if del_ids:
        conn.execute("DELETE FROM events WHERE id IN ({})".format(
            ",".join(str(x) for x in del_ids)
        ))
        print(f"  去重: 删除 {len(del_ids)} 条（同名+同时间）")

    # 统一事件日期格式
    date_rows = conn.execute("SELECT id, game_id, test_name, test_time, status FROM events").fetchall()
    date_groups = {}
    for r in date_rows:
        nd = normalize_date(r[3])
        key = (r[1], r[2], nd)
        date_groups.setdefault(key, []).append((r[0], r[3], r[4]))
    del_date_ids = []
    for key, group in date_groups.items():
        if len(group) < 2:
            continue
        status_order = {'正常': 0, '新增': 1, '待审': 2}
        group.sort(key=lambda x: status_order.get(x[2], 3))
        for dup in group[1:]:
            del_date_ids.append(dup[0])
    if del_date_ids:
        conn.execute("DELETE FROM events WHERE id IN ({})".format(
            ",".join(str(x) for x in del_date_ids)))
        print(f"  删除日期重复: {len(del_date_ids)} 条")
    for row in conn.execute("SELECT id, test_time FROM events"):
        nd = normalize_date(row[1])
        if nd != row[1]:
            conn.execute("UPDATE events SET test_time=? WHERE id=?", (nd, row[0]))

    # 同游戏+同日期+同节点类型去重
    dup_ids = conn.execute("""
        SELECT e.id FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY game_id, test_time, test_type
                ORDER BY CASE status
                    WHEN '正常' THEN 0
                    WHEN '新增' THEN 1
                    WHEN '待审' THEN 2
                    ELSE 3
                END, id
            ) AS rn
            FROM events
        ) e WHERE e.rn > 1
    """).fetchall()
    if dup_ids:
        ids = [str(r[0]) for r in dup_ids]
        conn.execute("DELETE FROM events WHERE id IN ({})".format(",".join(ids)))
        print(f"  删除重复（正常>新增>待审）: {len(ids)} 条")

    # 超过 2 天的"新增"自动降为"正常"
    conn.execute("UPDATE events SET status='正常' WHERE status='新增' AND scrape_date < date('now', '-2 days')")
    cnt = conn.execute("SELECT changes()").fetchone()[0]
    if cnt:
        print(f"  旧新增→正常: {cnt} 条（爬取日期超过2天）")

    conn.commit()
    conn.close()

    # ==================== 公众号+平台合并逻辑 ====================
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    pa_normal = conn.execute("""
        SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
               e.log_text, e.source, e.tip_links, e.link, e.rating, e.download_count,
               e.need_code, e.is_wiped, e.is_formal
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        WHERE e.source_type = 'public_account' AND e.status = '正常'
    """).fetchall()

    scrape_all = conn.execute("""
        SELECT e.id, g.clean_name, g.display_name, e.test_name, e.test_time, e.test_type,
               e.log_text, e.source, e.tip_links, e.link, e.rating, e.download_count,
               e.need_code, e.is_wiped, e.is_formal
        FROM events e JOIN games g ON e.game_id = g.id LEFT JOIN reviews rv ON e.id = rv.event_id
        WHERE e.source_type = 'scrape'
    """).fetchall()

    def fuzzy_match_game(name_a, name_b):
        if not name_a or not name_b:
            return False
        a = name_a.lower().strip()
        b = name_b.lower().strip()
        if a == b:
            return True
        if a in b or b in a:
            return True
        clean_a = re.sub(r'[-\-\s].*', '', a).strip()
        clean_b = re.sub(r'[-\-\s].*', '', b).strip()
        if clean_a == clean_b:
            return True
        if clean_a in clean_b or clean_b in clean_a:
            return True
        return False

    merged_count = 0
    for pa in pa_normal:
        pa_id = pa["id"]
        pa_name = pa["clean_name"]
        pa_time = pa["test_time"]
        pa_type = pa["test_type"]

        for sc in scrape_all:
            sc_id = sc["id"]
            sc_name = sc["clean_name"]

            existing = conn.execute(
                "SELECT merged_source FROM events WHERE id=?", (sc_id,)
            ).fetchone()
            if existing and existing[0]:
                continue

            if not fuzzy_match_game(pa_name, sc_name):
                continue
            if pa_time != sc["test_time"]:
                continue
            if pa_type != sc["test_type"]:
                continue

            sc_log = sc["log_text"] or ""
            sc_source = sc["source"] or "爬取"
            if sc_log:
                merged_log = f"【{sc_source}日志】\\n{sc_log}"
                cur_log = conn.execute("SELECT log_text FROM events WHERE id=?", (pa_id,)).fetchone()
                if cur_log and cur_log[0]:
                    merged_log = cur_log[0] + "\\n\\n" + merged_log
                conn.execute("UPDATE events SET log_text=?, merged_source=?, source=? WHERE id=?", (
                    merged_log, sc_source, f"公众号+{sc_source.replace('-', '')}", pa_id
                ))
            else:
                conn.execute("UPDATE events SET merged_source=?, source=? WHERE id=?", (
                    sc_source, f"公众号+{sc_source.replace('-', '')}", pa_id
                ))

            conn.execute("UPDATE events SET merged_source=?, status='正常' WHERE id=?", (
                f"merged_to_{pa_id}", sc_id
            ))

            merged_count += 1

    if merged_count:
        print(f"  公众号+平台合并完成: {merged_count} 条")

    # 手动审核节点覆盖同游戏+同时间的其他节点
    manual_rows = conn.execute("""
        SELECT e.id, g.clean_name, e.test_time
        FROM events e JOIN games g ON e.game_id = g.id
        WHERE e.manual_reviewed = 1
    """).fetchall()
    for r in manual_rows:
        eid, cname, ttime = r["id"], r["clean_name"], r["test_time"]
        conn.execute("""
            DELETE FROM events WHERE game_id IN (
                SELECT id FROM games WHERE clean_name=?
            ) AND test_time=? AND id!=? AND (manual_reviewed IS NULL OR manual_reviewed=0)
        """, (cname, ttime, eid))

    conn.commit()
    conn.close()
