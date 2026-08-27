# -*- coding: utf-8 -*-
"""
游戏节点数据看板 - 主入口
爬虫、AI提取、数据库、HTML生成、API服务一体化
"""
import sys
import io
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(line_buffering=True)

import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import re
import json

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "games_history.db")
PUBLIC_ACCOUNT_DIR = os.path.join(BASE_DIR, "公众号数据")

# === 导入模块化组件 ===
from config_manager import init_configs, get_hot_config, get_reserve_config
from ai_caller import call_ai
from scraper.utils import (
    html_to_text, classify_source_by_url, normalize_date, parse_test_time,
    classify_test_type, needs_code, is_wiped, is_formal_operation,
    clean_download_count, normalize_row, get_taptap_hotness
)
from scraper.taptap import (
    scrape_taptap_reserve, scrape_taptap_in_app_event
)

from database.schema import init_db
from database.operations import save_to_sqlite, query_game, extract_urls, clean_tip_links
from html_generator.calendar import generate_calendar
from html_generator.kanban import generate_kanban
from html_generator.schedule import generate_test_schedule
from api_server import start_api_server
from merger import normalize_game_name, normalize_test_name, merge_duplicates


# ==================== 主流程 ====================

def main():
    init_configs()
    init_db()

    print("开始采集...")
    all_data = []
    all_data.extend(scrape_taptap_reserve())
    all_data.extend(scrape_taptap_in_app_event())


    if all_data:
        df = pd.DataFrame(all_data)
        df['下载/预约数'] = df['下载/预约数'].apply(clean_download_count)
        df['所属游戏(纯净)'] = df['所属游戏'].apply(normalize_game_name)
        df = merge_duplicates(df)
        cols = [
            "所属游戏", "所属游戏(纯净)", "测试名称", "测试时间", "测试类型",
            "需要激活码", "是否删档", "服务器地区", "是否正式运营",
            "评价数", "下载/预约数", "温馨提示链接", "最新动态链接", "日志原文", "链接", "来源"
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
        save_to_sqlite(df)
        print(f"已保存 {len(df)} 条")

    # 导入公众号 + 合并
    import public_account as _pa
    _pa.import_all_public_account_sheets()
    import merger as _merger
    _merger.merge_sources()

    print("生成看板...")
    generate_calendar()
    generate_kanban()
    generate_test_schedule()
    print("所有看板已生成")


def _run_full_pipeline(api_url=None):
    """完整流水线：采集 → 数据库 → 公众号导入 → 合并 → 生成看板"""
    import time as _time
    import public_account as _pa
    import merger as _merger
    init_configs()
    init_db()

    print("开始采集...")
    all_data = []
    all_data.extend(scrape_taptap_reserve())
    all_data.extend(scrape_taptap_in_app_event())


    if all_data:
        df = pd.DataFrame(all_data)
        df['下载/预约数'] = df['下载/预约数'].apply(clean_download_count)
        df['所属游戏(纯净)'] = df['所属游戏'].apply(normalize_game_name)
        df = merge_duplicates(df)
        cols = [
            "所属游戏", "所属游戏(纯净)", "测试名称", "测试时间", "测试类型",
            "需要激活码", "是否删档", "服务器地区", "是否正式运营",
            "评价数", "下载/预约数", "温馨提示链接", "最新动态链接", "日志原文", "链接", "来源"
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
        save_to_sqlite(df)
        print(f"已保存 {len(df)} 条")

    _pa.import_all_public_account_sheets()
    _merger.merge_sources()

    print("生成看板...")
    generate_calendar(api_url=api_url)
    generate_kanban(api_url=api_url)
    generate_test_schedule()
    print("所有看板已生成")


def _regenerate_html(api_url=None):
    """仅重新生成 HTML（不采集）"""
    init_db()
    print("生成看板...")
    generate_calendar(api_url=api_url)
    generate_kanban(api_url=api_url)
    generate_test_schedule()
    print("所有看板已生成")


def start_serve(port=8765):
    """启动看板服务（只开服务 + 生成已有数据，采集靠页面按钮触发）"""
    import time as _time
    import threading as _threading
    import subprocess as _sp
    api_url = f"http://127.0.0.1:{port}"
    _regenerate_html(api_url=api_url)
    _server_thread = _threading.Thread(target=start_api_server, args=(port,), daemon=True)
    _server_thread.start()
    _time.sleep(1.5)
    try:
        _sp.Popen(["cmd", "/c", "start", "", api_url], shell=True)
    except Exception:
        pass
    print(f"服务运行于 {api_url} (Ctrl+C 停止)")
    try:
        while True:
            _time.sleep(10)
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--query" and len(sys.argv) > 2:
            rows = query_game(sys.argv[2])
            for r in rows:
                print(dict(r))
        elif arg == "--scrape":
            main()
        elif arg == "--merge":
            import public_account as _pa
            import merger as _merger
            init_db()
            _pa.import_all_public_account_sheets()
            _merger.merge_sources()
        elif arg == "--clean-links":
            clean_tip_links()
        elif arg == "--serve":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
            start_serve(port)
        elif arg == "--pipeline":
            _run_full_pipeline()
        else:
            print("可用参数: --query <游戏名> | --scrape | --merge | --clean-links | --serve [端口] | --pipeline")
    else:
        main()
