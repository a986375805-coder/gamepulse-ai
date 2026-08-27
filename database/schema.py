"""数据库初始化与 schema 版本管理"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "games_history.db")
SCHEMA_VERSION = 2


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )""")
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cur.fetchone()
    current_ver = row[0] if row[0] else 0

    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clean_name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            first_seen TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            test_time TEXT NOT NULL,
            test_type TEXT NOT NULL,
            need_code TEXT DEFAULT '',
            is_wiped TEXT DEFAULT '',
            server_region TEXT DEFAULT '',
            is_formal TEXT DEFAULT '',
            rating TEXT DEFAULT '',
            download_count TEXT DEFAULT '',
            tip_links TEXT DEFAULT '',
            latest_link TEXT DEFAULT '',
            log_text TEXT DEFAULT '',
            link TEXT DEFAULT '',
            source TEXT DEFAULT '',
            scrape_date TEXT NOT NULL,
            status TEXT DEFAULT '新增',
            source_type TEXT DEFAULT 'scrape',
            exported INTEGER DEFAULT 0,
            removed_from_schedule INTEGER DEFAULT 0,
            manual_edit INTEGER DEFAULT 0,
            manual_reviewed INTEGER DEFAULT 0,
            merged_source TEXT DEFAULT '',
            FOREIGN KEY (game_id) REFERENCES games(id),
            UNIQUE(game_id, test_name, test_time)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_game ON events(game_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(test_time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")

    if current_ver < 1:
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")

    if current_ver < 2:
        conn.execute("""CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL UNIQUE,
            review_date TEXT NOT NULL,
            verdict TEXT DEFAULT 'pending',
            confidence TEXT,
            reasoning TEXT,
            sources TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS public_account_sheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            import_date TEXT NOT NULL,
            record_count INTEGER DEFAULT 0
        )""")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")

    conn.commit()
    conn.close()
