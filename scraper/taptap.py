"""TapTap 预约榜 + 新版本榜爬虫"""

import re
import time
import requests
from datetime import datetime

from config_manager import get_hot_config, get_reserve_config
from ai_caller import call_ai
from scraper.utils import (
    html_to_text, parse_test_time, classify_test_type,
    needs_code, is_wiped, normalize_row, get_taptap_hotness
)


TAPTAP_XUA = "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC&DS=Android&UID=db88ea35-c18e-424c-acfd-11655e101a6d&OS=Windows&OSV=NT&DT=PC"


def fetch_reserve_list(max_pages=5):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    base = "https://www.taptap.cn/webapiv2/app-top/v2/hits"
    games = []
    for page in range(max_pages):
        from_val = page * 10
        url = f"{base}?X-UA={requests.utils.quote(TAPTAP_XUA)}&type_name=reserve&from={from_val}&limit=10"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            lst = data.get("data", {}).get("list", [])
            for item in lst:
                app = item.get("app", {})
                title = app.get("title", "")
                app_id = app.get("id")
                if title and app_id:
                    games.append((title, f"https://www.taptap.cn/app/{app_id}"))
            if len(lst) < 10:
                break
        except Exception as e:
            print(f"    获取预约榜列表失败: {e}")
            break
        time.sleep(0.3)
    return games


def scrape_taptap_reserve():
    print("\n" + "=" * 60)
    print("【TapTap 预约榜】")
    print("=" * 60)
    print(f"  正在获取预约榜列表...", flush=True)
    reserve_games = fetch_reserve_list()
    print(f"  获取到 {len(reserve_games)} 款预约游戏\n")
    results = []
    for i, (name, url) in enumerate(reserve_games, 1):
        print(f"  [{i:>2}/{len(reserve_games)}] {name} ...", end=" ", flush=True)
        try:
            resp = requests.get(url + "?os=android", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"页面失败: {e}")
            continue
        text = html_to_text(resp.text)
        prompt = f"""从以下 TapTap 游戏页面中提取测试/上线信息，返回 JSON。

字段:
- game_name: 游戏名称
- test_name: 测试名称（如"破晓号测试""火种测试"），首发/公测填"首发"，没有填"—"
- test_time_raw: 测试日期原文（如"2026/05/28""2026/06/19""待公布""26年Q3"等），没有填"—"
- test_type_raw: 测试类型原文（如"限量删档计费""不限量不删档计费""首发""公测"等），没有填"—"
- has_activation: 是否需要激活码/抢资格（限量=是、首发/公测=否），填"是"或"否"或"—"
- is_wiped: 是否删档（删档=是、不删档=否），填"是"或"否"或"—"

游戏名称: {name}

页面内容:
{text[:6000]}"""
        info = call_ai(get_reserve_config(), prompt, ["game_name", "test_name", "test_time_raw", "test_type_raw", "has_activation", "is_wiped"])
        if not info or not info.get("test_name") or info["test_name"] in ("—", ""):
            print("AI无结果")
            continue
        test_name = info.get("test_name", "—")
        test_time_raw = info.get("test_time_raw", "—")
        test_type_raw = info.get("test_type_raw", "—")
        parsed = parse_test_time(test_time_raw)
        if not parsed:
            print(f"跳过(无有效时间: {test_time_raw})")
            continue
        test_type = classify_test_type(test_type_raw, test_name)
        code = needs_code(test_name, test_type_raw)
        wiped = is_wiped(test_type_raw)
        hotness = get_taptap_hotness(url)
        rating = hotness["评价数"] if hotness else ""
        download_reserve = hotness["下载/预约数"] if hotness else ""
        results.append(normalize_row(
            info.get("game_name", name), test_name, parsed,
            test_type, code, wiped, url, "TapTap预约榜",
            rating=rating, download_reserve=download_reserve
        ))
        print(f"OK ({parsed})")
        time.sleep(0.3)
    print(f"  → 预约榜获取 {len(results)} 条")
    return results


def scrape_taptap_in_app_event():
    """TapTap 新版本榜（应用内活动预约）"""
    print("\n" + "=" * 60)
    print("【TapTap 新版本榜】")
    print("=" * 60)
    base_api = (
        'https://www.taptap.cn/webapiv2/app-top/v2/hits'
        f'?X-UA={requests.utils.quote(TAPTAP_XUA)}'
    )
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    all_items = []
    for start in range(0, 200, 10):
        url = f"{base_api}&type_name=in_app_event_reserve&from={start}&limit=10"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            data = resp.json()
            items = data.get('data', {}).get('list', [])
            all_items.extend(items)
            print(f"  请求新版本榜 {start}-{start+9}: 获取到 {len(items)} 个")
        except Exception as e:
            print(f"  获取新版本榜失败: {e}")
        if len(items) < 10:
            break
        time.sleep(0.3)

    results = []
    for i, item in enumerate(all_items):
        event = item.get('in_app_event', {})
        if not event:
            continue
        app_card = event.get('app_card', {})
        game_name = app_card.get('title', '')
        app_id = app_card.get('id')
        if not game_name or not app_id:
            continue

        event_title = event.get('title', '')
        whatsnew = event.get('whatsnew', '')
        release_ts = event.get('release_time')
        reserve_count = event.get('stat', {}).get('reserve_count', 0)

        event_date = ""
        if release_ts:
            dt = datetime.fromtimestamp(release_ts)
            event_date = f"{dt.year}/{dt.month:02d}/{dt.day:02d}"

        download_str = ""
        if reserve_count:
            if reserve_count >= 10000:
                download_str = f"{reserve_count/10000:.1f}万预约"
            else:
                download_str = f"{reserve_count}预约"

        link = f"https://www.taptap.cn/app/{app_id}"

        test_type = "新版本"
        tags = [t.get('key', '') for t in event.get('tags', [])]
        if any('publish' in t or 'launch' in t or 'first' in t for t in tags):
            test_type = "公测"
        if any('new_season' in t or 'update' in t for t in tags):
            test_type = "新版本"

        print(f"  [{i+1}/{len(all_items)}] {game_name} → {event_title} / {event_date} / {test_type}")
        results.append(normalize_row(
            game_name, event_title, event_date, test_type,
            "否", "否", link, "TapTap新版本榜",
            download_reserve=download_str
        ))
        time.sleep(0.2)

    print(f"  → 新版本榜获取 {len(results)} 条")
    return results
