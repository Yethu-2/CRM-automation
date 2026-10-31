"""SQLite: conversations, their messages (in the exact shape sent to DeepSeek) and one row per assistant turn."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, model TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS messages (conv_id TEXT, ix INTEGER, message TEXT, PRIMARY KEY (conv_id, ix));
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT, created_at REAL, model TEXT,
  question TEXT, latency_ms INTEGER, prompt_tokens INTEGER, cache_hit_tokens INTEGER, completion_tokens INTEGER,
  cost_usd REAL, tool_calls INTEGER, skills_loaded TEXT, trace TEXT, error TEXT, user_email TEXT);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def new_conversation(model: str) -> dict:
    conv = {"id": uuid.uuid4().hex[:12], "title": "New chat", "model": model, "created_at": time.time()}
    with connect() as c:
        c.execute("INSERT INTO conversations VALUES (:id, :title, :model, :created_at)", conv)
    return conv


def list_conversations() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM conversations ORDER BY created_at DESC LIMIT 200")]


def get_conversation(conv_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        if not row:
            return None
        msgs = [json.loads(r[0]) for r in c.execute("SELECT message FROM messages WHERE conv_id = ? ORDER BY ix", (conv_id,))]
        runs = [_run(r) for r in c.execute("SELECT * FROM runs WHERE conv_id = ? ORDER BY id", (conv_id,))]
    return {**dict(row), "messages": msgs, "runs": runs}


def delete_conversation(conv_id: str) -> None:
    with connect() as c:
        for t, col in (("messages", "conv_id"), ("runs", "conv_id"), ("conversations", "id")):
            c.execute(f"DELETE FROM {t} WHERE {col} = ?", (conv_id,))


def append_messages(conv_id: str, messages: list[dict], *, title: str | None = None, model: str | None = None) -> None:
    with connect() as c:
        n = c.execute("SELECT COALESCE(MAX(ix), -1) + 1 FROM messages WHERE conv_id = ?", (conv_id,)).fetchone()[0]
        c.executemany("INSERT INTO messages VALUES (?, ?, ?)",
                      [(conv_id, n + i, json.dumps(m, ensure_ascii=False)) for i, m in enumerate(messages)])
        if title:
            c.execute("UPDATE conversations SET title = ? WHERE id = ? AND title = 'New chat'", (title[:80], conv_id))
        if model:
            c.execute("UPDATE conversations SET model = ? WHERE id = ?", (model, conv_id))


def add_run(conv_id: str, question: str, done: dict[str, Any] | None, error: str | None, user_email: str | None) -> None:
    d = done or {}
    u = d.get("usage") or {}
    with connect() as c:
        c.execute("INSERT INTO runs (conv_id, created_at, model, question, latency_ms, prompt_tokens, cache_hit_tokens, "
                  "completion_tokens, cost_usd, tool_calls, skills_loaded, trace, error, user_email) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (conv_id, time.time(), d.get("model"), question[:2000], d.get("latency_ms"), u.get("prompt_tokens"),
                   u.get("prompt_cache_hit_tokens"), u.get("completion_tokens"), d.get("cost_usd"), len(d.get("tools") or []),
                   json.dumps(d.get("skills_loaded") or []), json.dumps(d.get("tools") or [], ensure_ascii=False), error, user_email))


def _run(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["skills_loaded"] = json.loads(d["skills_loaded"] or "[]")
    d["trace"] = json.loads(d["trace"] or "[]")
    return d


CSV_FIELDS = ["id", "created_at", "conv_id", "model", "question", "latency_ms", "prompt_tokens", "cache_hit_tokens",
              "completion_tokens", "cost_usd", "tool_calls", "skills_loaded", "error", "user_email"]


def runs_csv() -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    with connect() as c:
        for r in c.execute("SELECT * FROM runs ORDER BY id"):
            row = dict(r)
            row["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(row["created_at"]))
            w.writerow(row)
    return out.getvalue()
