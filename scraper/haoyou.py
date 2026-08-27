"""好游快爆 时间线爬虫"""

import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from config_manager import get_hot_config
from ai_caller import call_ai
from scraper.utils import normalize_row


_MINOR_EVENT_KEYWORDS = [
    '皮肤', '外观', '时装', '新皮肤', '新外观',
    '卡池', '新卡池', '新角色', '新武器', '新装备',
    '活动', '新活动', '签到', '礼包', '新礼包',
    '赛季更新', '赛季末', '赛季结算',
    '每周', '每日', '例行维护', '不停机',
]


def clean_haoyou_name(name):
    name = re.sub(r'[（(]?(官服|正版|手机版|安卓版|国服|国际服|手游版|移动版)[）)]?', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def is_minor_event(test_name, test_type, log_text):
    if test_type == "日常更新":
        return True
    combined = (test_name + " " + (log_text or "")).lower()
    for kw in _MINOR_EVENT_KEYWORDS:
        if kw.lower() in combined:
            return True
    return False


def get_haoyou_hotness(detail_url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(detail_url, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")
        result = {"评价数": "", "下载/预约数": ""}
        pl_num = soup.find(id="pl_num")
        if pl_num:
            result["评价数"] = pl_num.text.strip()
        sp_info = soup.select_one("p.sp-info")
        if sp_info:
            from copy import deepcopy
            sp_copy = deepcopy(sp_info)
            score_span = sp_copy.find("span", class_="score")
            if score_span:
                score_span.decompose()
            text = sp_copy.get_text(strip=True)
            match = re.search(r'([\d.]+万?)(下载人数|预约人数)', text)
            if match:
                result["下载/预约数"] = match.group(1) + match.group(2)
        return result
    except Exception as e:
        print(f"      好游热度获取失败: {e}")
        return None


def haoyou_map_test_type(t, test_name=""):
    if not t and not test_name:
        return "日常更新"
    combined = (t or "") + " " + (test_name or "")
    if re.search(r'公测|首发|上线|发布|发售|开服|开测', combined):
        return "公测"
    if re.search(r'内测|限量|删档|激活码', combined) and "不删档" not in combined:
        return "内测"
    if re.search(r'封测', combined):
        return "封测"
    if re.search(r'资料片|资料篇|DLC', combined):
        return "资料片"
    if re.search(r'新版本|版本更新|新版|赛季|S\d', combined):
        return "新版本"
    if re.search(r'预约', combined):
        return "内测"
    if re.search(r'日常更新|每周|例行|活动|维护', combined):
        return "日常更新"
    t_clean = (t or "").strip()
    if t_clean in ("公测", "内测", "封测", "新版本", "资料片", "日常更新"):
        return t_clean
    return "公测"


def scrape_haoyou():
    print("\n" + "=" * 60)
    print("【好游快爆时间线】")
    print("=" * 60)
    url = "https://www.3839.com/timeline.html"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"请求好游快爆失败: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    fore_area = soup.find("div", class_="foreArea")
    if not fore_area:
        print("未找到 foreArea 区域")
        return []

    today = datetime.now()
    yesterday = today - timedelta(days=1)
    games_by_name = {}

    for foreCard in fore_area.find_all("div", class_="foreCard"):
        hd = foreCard.find("div", class_="foreCard-hd")
        if not hd:
            continue
        date_str = hd.get_text(strip=True)
        if "抢先爆料" in date_str:
            continue
        date_match = re.search(r"(\d{1,2})月(\d{1,2})日", date_str)
        if not date_match:
            continue
        test_date = f"{date_match.group(1)}月{date_match.group(2)}日"
        card_date = datetime(today.year, int(date_match.group(1)), int(date_match.group(2)))
        if card_date < yesterday.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        for li in foreCard.find_all("li"):
            name_tag = li.find("div", class_="name")
            if not name_tag:
                continue
            em = name_tag.find("em")
            if not em:
                continue
            game_name = clean_haoyou_name(em.get_text(strip=True))
            if not game_name:
                continue
            link = ""
            a_tag = li.find("a")
            if a_tag and a_tag.get("href"):
                href = a_tag["href"]
                link = "https:" + href if href.startswith("//") else "https://www.3839.com" + href
            if game_name not in games_by_name:
                games_by_name[game_name] = []
            games_by_name[game_name].append({"date": test_date, "link": link})

    results = []
    total = len(games_by_name)
    for idx, (game_name, events) in enumerate(games_by_name.items()):
        print(f"  [{idx+1}/{total}] {game_name}...", end=" ", flush=True)
        try:
            best = events[0]
            log_text = ""
            tip_links = ""
            latest_link = ""
            raw_log = ""
            if best["link"]:
                try:
                    log_resp = requests.get(best["link"], headers=headers, timeout=15)
                    log_resp.encoding = "utf-8"
                    log_soup = BeautifulSoup(log_resp.text, "lxml")
                    log_parts = []
                    lb_news = log_soup.find("div", class_="lb-news")
                    if lb_news:
                        log_parts.append(lb_news.get_text(strip=True))
                    game_log = log_soup.find("div", class_="game-log")
                    if game_log:
                        log_parts.append(game_log.get_text(strip=True))
                    log_text = "\n".join(log_parts).strip()
                    sp_txt_divs = log_soup.find_all("div", class_="sp-txt")
                    link_urls = []
                    for div in sp_txt_divs:
                        for a in div.find_all("a", href=True):
                            href = a["href"]
                            if href.startswith("//"):
                                href = "https:" + href
                            if href and href not in ("#", "javascript:void(0)") and href not in link_urls:
                                link_urls.append(href)
                                if len(link_urls) >= 3:
                                    break
                        if len(link_urls) >= 3:
                            break
                    if link_urls:
                        tip_links = " ".join(link_urls[:3])
                    warm = log_soup.find("div", class_="lb-warm-li")
                    if warm:
                        warm_a = warm.find("a")
                        if warm_a and warm_a.get("href"):
                            latest_link = warm_a["href"]
                            if latest_link.startswith("//"):
                                latest_link = "https:" + latest_link
                    log_a = log_soup.find("a", id="game_open_log_a")
                    if log_a:
                        raw_log = log_a.get_text(strip=True)
                except Exception:
                    pass

            has_event = any(k in (log_text + game_name) for k in [
                '测试', '公测', '内测', '封测', '首发', '上线', '新版本',
                '版本更新', '资料片', '预约', '激活'
            ])
            if not has_event and len(log_text) < 50:
                print("无事件关键词，跳过")
                continue

            if not log_text or len(log_text.strip()) < 20:
                test_name = "日常更新"
                test_type = "日常更新"
                code = "否"
                wiped = "否"
            else:
                current_date = datetime.now().strftime("%Y-%m-%d")
                prompt = f"""你是一个专业的游戏运营数据提取助手。请根据下面的游戏更新日志，提取出该游戏的一个**最重要的节点信息**（如公测、内测、新版本等）。

**游戏名称**：{game_name}
**来源平台**：好游快爆
**日志内容**：
{log_text[:2500]}

**当前日期**：{current_date}

**提取字段规则**：
1. **测试名称** (test_name): 本次节点的事件名称，最多15字。
2. **测试日期** (test_date): 格式 YYYY-MM-DD，无法确定则留空。
3. **测试类型** (test_type): 从 [公测, 内测, 封测, 新版本, 资料片, 预约, 日常更新] 中选择。
4. **是否删档** (is_delete): 是/否
5. **是否需要激活码** (need_code): 是/否

**输出格式**：只输出一个合法的 JSON 对象。无法提取的字段留空字符串。"""
                ai_result = call_ai(get_hot_config(), prompt, ["test_name", "test_date", "test_type", "is_delete", "need_code"])
                test_name = ai_result.get("test_name", "") or "日常更新"
                test_type = haoyou_map_test_type(ai_result.get("test_type", ""), test_name)
                code = ai_result.get("need_code", "否") or "否"
                wiped = ai_result.get("is_delete", "否") or "否"

            if is_minor_event(test_name, test_type, log_text):
                print(f"跳过小更新: {test_name} / {test_type}")
                continue

            final_date = ""
            m = re.search(r"(\d{1,2})月(\d{1,2})日", best["date"])
            if m:
                final_date = f"{datetime.now().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if not final_date:
                print(f"无有效日期，跳过")
                continue

            dt = datetime.strptime(final_date[:10], "%Y-%m-%d")
            parsed = f"{dt.year}/{dt.month:02d}/{dt.day:02d}"
            link = best["link"]
            hotness = get_haoyou_hotness(link)
            rating = hotness["评价数"] if hotness else ""
            download_reserve = hotness["下载/预约数"] if hotness else ""

            results.append(normalize_row(
                game_name, test_name, parsed, test_type, code, wiped, link, "好游快爆",
                rating=rating, download_reserve=download_reserve,
                tip_links=tip_links, latest_link=latest_link, log_text=raw_log
            ))
            print(f"\u2192 {test_name} / {parsed} / {test_type}")
        except Exception as e:
            print(f"    处理失败: {e}")
            continue
    print(f"  \u2192 好游快爆获取 {len(results)} 条")
    return results
