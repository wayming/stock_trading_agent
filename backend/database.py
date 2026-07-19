"""SQLite database initialization and CRUD helpers."""

import sqlite3
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH


class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
        self._db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._db_conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def create_schema(self):
        """Create database directory and tables, including migrations."""
        with self._lock:
            self._db_conn.row_factory = sqlite3.Row
            self._db_conn.execute("PRAGMA journal_mode=WAL")
            self._db_conn.executescript("""
                CREATE TABLE IF NOT EXISTS news (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    symbol TEXT DEFAULT '',
                    timestamp TEXT DEFAULT '',
                    raw_json TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS sentiment_results (
                    id TEXT PRIMARY KEY,
                    news_id TEXT NOT NULL,
                    sentiment TEXT NOT NULL,
                    confidence_score REAL DEFAULT 0.0,
                    reasoning TEXT DEFAULT '',
                    prompt TEXT DEFAULT '',
                    llm_response TEXT DEFAULT '',
                    trade_action TEXT DEFAULT 'NONE',
                    conversation TEXT DEFAULT '',
                    timestamp TEXT DEFAULT '',
                    FOREIGN KEY(news_id) REFERENCES news(id)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    news_id TEXT NOT NULL,
                    sentiment_result_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    symbol TEXT DEFAULT '',
                    entry_price REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'OPEN',
                    pnl REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT '',
                    closed_at TEXT,
                    FOREIGN KEY(news_id) REFERENCES news(id)
                );
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            self._migrate()
            self._db_conn.commit()

    def _migrate(self):
        """Add missing columns to existing tables."""
        migrations = [
            "ALTER TABLE sentiment_results ADD COLUMN conversation TEXT DEFAULT ''",
        ]
        for sql in migrations:
            try:
                self._db_conn.execute(sql)
            except sqlite3.OperationalError:
                pass

    def close(self):
        with self._lock:
            if self._db_conn:
                self._db_conn.close()
                self._db_conn = None

    # ── News ─────────────────────────────────────────────

    def insert_news(self, item: dict) -> str:
        with self._lock:
            news_id = item.get("id") or str(uuid.uuid4())
            self._db_conn.execute(
                """INSERT OR IGNORE INTO news (id, content, source, symbol, timestamp, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    news_id,
                    item.get("content", ""),
                    item.get("source", ""),
                    item.get("symbol", ""),
                    item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    item.get("raw_json", ""),
                ),
            )
            self._db_conn.commit()
            return news_id

    def get_news(self, news_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db_conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
            return dict(row) if row else None

    def list_news(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._db_conn.execute(
                "SELECT * FROM news ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Sentiment Results ────────────────────────────────

    def insert_sentiment_result(self, item: dict) -> str:
        with self._lock:
            result_id = item.get("id") or str(uuid.uuid4())
            self._db_conn.execute(
                """INSERT OR IGNORE INTO sentiment_results
                (id, news_id, sentiment, confidence_score, reasoning, prompt, llm_response, trade_action, conversation, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result_id,
                    item["news_id"],
                    item.get("sentiment", "neutral"),
                    item.get("confidence_score", 0.0),
                    item.get("reasoning", ""),
                    item.get("prompt", ""),
                    item.get("llm_response", ""),
                    item.get("trade_action", "NONE"),
                    item.get("conversation", ""),
                    item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                ),
            )
            self._db_conn.commit()
            return result_id

    def get_sentiment_result(self, result_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db_conn.execute(
                """SELECT sr.*, n.symbol, n.source
                FROM sentiment_results sr
                LEFT JOIN news n ON sr.news_id = n.id
                WHERE sr.id = ?""",
                (result_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_sentiment_results(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db_conn.execute(
                """SELECT sr.*, n.symbol, n.source
                FROM sentiment_results sr
                LEFT JOIN news n ON sr.news_id = n.id
                ORDER BY sr.timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_sentiment_by_news(self, news_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db_conn.execute(
                "SELECT * FROM sentiment_results WHERE news_id = ? ORDER BY timestamp DESC LIMIT 1",
                (news_id,),
            ).fetchone()
            return dict(row) if row else None

    # ── Trades ───────────────────────────────────────────

    def insert_trade(self, item: dict) -> str:
        with self._lock:
            trade_id = item.get("id") or str(uuid.uuid4())
            self._db_conn.execute(
                """INSERT OR IGNORE INTO trades
                (id, news_id, sentiment_result_id, action, symbol, entry_price, status, pnl, created_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_id,
                    item["news_id"],
                    item.get("sentiment_result_id", ""),
                    item.get("action", "NONE"),
                    item.get("symbol", ""),
                    item.get("entry_price", 0.0),
                    item.get("status", "OPEN"),
                    item.get("pnl", 0.0),
                    item.get("created_at", datetime.now(timezone.utc).isoformat()),
                    item.get("closed_at"),
                ),
            )
            self._db_conn.commit()
            return trade_id

    def get_positions(self) -> list[dict]:
        with self._lock:
            rows = self._db_conn.execute(
                "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db_conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def close_trade(self, trade_id: str, exit_price: float, pnl: float, closed_at: str):
        with self._lock:
            self._db_conn.execute(
                """UPDATE trades
                   SET status = 'CLOSED', pnl = ?, closed_at = ?
                   WHERE id = ?""",
                (pnl, closed_at, trade_id),
            )
            self._db_conn.commit()

    # ── Config ───────────────────────────────────────────

    def get_config(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._db_conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_config(self, key: str, value: str):
        with self._lock:
            self._db_conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
            )
            self._db_conn.commit()

    def get_config_float(self, key: str, default: float = 0.0) -> float:
        val = self.get_config(key)
        return float(val) if val is not None else default
