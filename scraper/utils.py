"""爬虫共享工具函数"""

import re
import json
import requests
from datetime import datetime, timedelta


def html_to_text(html):
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    html = re.sub(r'</?(?:div|p|br|li|h[1-6]|tr|td|section|header|footer|span|a)[^>]*>', '\n', html)
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()


def classify_source_by_url(url):
    if not url:
        return None
    u = url.lower()
    if "steam" in u or "store.steampowered" in u:
        return "Steam"
    if "mp.weixin.qq.com" in u:
        return "公众号"
    if "3839.com" in u:
        return "好游快爆"
    if "taptap" in u or "tap.io" in u:
        return "TapTap"
    return None


def normalize_date(s):
    if not s:
        return s
    s = str(s).strip().split()[0]
    m = re.match(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def parse_test_time(raw):
    if not raw or raw in ("—", "待公布", ""):
        return None
    today = datetime.now()
    cutoff = today - timedelta(days=30)
    def in_window(dt):
        return dt >= cutoff
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', raw)
    if m:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if in_window(dt):
            return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
        return None
    m = re.search(r'(\d{1,2})月(\d{1,2})日', raw)
    if m:
        dt = datetime(2026, int(m.group(1)), int(m.group(2)))
        if in_window(dt):
            return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
        return None
    m = re.search(r'(\d{2})年Q(\d)', raw)
    if m:
        return f"{int(m.group(1))+2000}/Q{m.group(2)}"
    return None


def classify_test_type(test_type_raw, test_name, is_launched=False):
    t = (test_type_raw or "") + " " + (test_name or "")
    if is_launched:
        if re.search(r'资料片|资料篇', t): return "资料片"
        if re.search(r'新版本|版本更新|新版|赛季|S\d', t): return "新版本"
        if re.search(r'日常更新|每周|例行', t): return "日常更新"
        if re.search(r'内测|限量|删档', t) and "不删档" not in t: return "内测"
        return "新版本"
    if re.search(r'首发|公测|正式上线', t): return "公测"
    if "不限量" in t and "不删档" in t: return "公测"
    if "封测" in t: return "封测"
    if "内测" in t: return "内测"
    if ("限量" in t or "删档" in t) and "不删档" not in t: return "内测"
    if "测试" in test_name and "首发" not in test_name: return "内测"
    return "公测"


def needs_code(test_name, test_type_raw, is_launched=False):
    if is_launched: return "否"
    t = (test_name or "") + " " + (test_type_raw or "")
    if re.search(r'首发|公测|正式上线', t): return "否"
    if "不限量" in t: return "否"
    if re.search(r'限量|激活码|抢资格|招募|线下', t): return "是"
    if "删档" in t: return "是"
    if test_type_raw and test_type_raw not in ("—", ""): return "是"
    return "否"


def is_wiped(test_type_raw):
    t = test_type_raw or ""
    if "不删档" in t: return "否"
    if "删档" in t: return "是"
    return "否"


def is_formal_operation(test_type):
    return "否" if test_type in ("内测", "封测") else "是"


def clean_download_count(val):
    if not val or not isinstance(val, str):
        return val
    val = re.sub(r'^\d\.\d', '', val)
    val = re.sub(r'(下载人数|预约人数|下载|预约)$', '', val)
    return val.strip()


def normalize_row(name, test_name, test_time, test_type, code, wiped, link, source,
                  rating="", download_reserve="", tip_links="", latest_link="", log_text=""):
    return {
        "所属游戏": name,
        "测试名称": test_name,
        "测试时间": test_time,
        "测试类型": test_type,
        "需要激活码": code,
        "是否删档": wiped,
        "服务器地区": "中国",
        "是否正式运营": is_formal_operation(test_type),
        "评价数": rating,
        "下载/预约数": download_reserve,
        "温馨提示链接": tip_links,
        "最新动态链接": latest_link,
        "日志原文": log_text,
        "链接": link,
        "来源": source,
    }


def get_taptap_hotness(app_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(app_url, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
        match = re.search(r'<script type="application/json" id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(1))
        rating_count = 0
        download_count = 0
        reserve_count = 0
        for i, item in enumerate(data):
            if isinstance(item, dict):
                if "review_count" in item:
                    idx = item["review_count"]
                    if isinstance(idx, int) and idx < len(data):
                        rating_count = data[idx]
                if "hits_total" in item:
                    idx = item["hits_total"]
                    if isinstance(idx, int) and idx < len(data):
                        download_count = data[idx]
                if "reserve_count" in item:
                    idx = item["reserve_count"]
                    if isinstance(idx, int) and idx < len(data):
                        reserve_count = data[idx]
        return {
            "\u8bc4\u4ef7\u6570": f"{rating_count:,}" if rating_count else "",
            "\u4e0b\u8f7d/\u9884\u7ea6\u6570": f"{download_count:,}" if download_count else (f"{reserve_count:,}" if reserve_count else "")
        }
    except Exception as e:
        print(f"      TapTap \u70ed\u5ea6\u83b7\u53d6\u5931\u8d25: {e}")
        return None
