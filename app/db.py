"""SQLite session store. Single file, zero setup."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                 id TEXT PRIMARY KEY,
                 module_id TEXT NOT NULL,
                 state TEXT NOT NULL,
                 created REAL NOT NULL,
                 updated REAL NOT NULL)"""
        )


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def save(session_id: str, module_id: str, state: dict) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            """INSERT INTO sessions (id, module_id, state, created, updated)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated=excluded.updated""",
            (session_id, module_id, json.dumps(state), now, now),
        )


def load(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(row[0]) if row else None
