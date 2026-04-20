import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class MetadataCache:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), check_same_thread=False)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")

    def get(self, key: str) -> Any | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        if time.time() > row[1]:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any, ttl: float) -> None:
        expires_at = time.time() + ttl
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), expires_at),
            )

    def cleanup_expired(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),))
