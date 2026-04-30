import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import List

DB_PATH = "ott_bot.db"
_lock = threading.Lock()


@contextmanager
def _conn():
    """Thread-safe SQLite connection context manager."""
    with _lock:
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id    INTEGER PRIMARY KEY,
                username   TEXT,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sent_items (
                item_id  TEXT PRIMARY KEY,
                title    TEXT,
                sent_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_stats (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)


# ─── Subscribers ──────────────────────────────────────────────────────────────

def add_subscriber(chat_id: int, username: str = "") -> bool:
    """Returns True if newly added, False if already existed."""
    with _conn() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id, username) VALUES (?, ?)",
            (chat_id, username or ""),
        )
        return cur.rowcount > 0


def remove_subscriber(chat_id: int) -> bool:
    """Returns True if removed, False if not found."""
    with _conn() as con:
        cur = con.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        return cur.rowcount > 0


def get_subscribers() -> List[int]:
    with _conn() as con:
        rows = con.execute("SELECT chat_id FROM subscribers").fetchall()
    return [row["chat_id"] for row in rows]


def get_subscriber_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]


def is_subscriber(chat_id: int) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row is not None


# ─── Sent items dedup ─────────────────────────────────────────────────────────

def is_item_sent(item_id: str) -> bool:
    with _conn() as con:
        return con.execute(
            "SELECT 1 FROM sent_items WHERE item_id = ?", (item_id,)
        ).fetchone() is not None


def mark_item_sent(item_id: str, title: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO sent_items (item_id, title, sent_at) VALUES (?, ?, ?)",
            (item_id, title, datetime.utcnow().isoformat()),
        )


def get_sent_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM sent_items").fetchone()[0]
