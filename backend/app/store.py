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
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, model TEXT, created_at REAL, user TEXT);
CREATE TABLE IF NOT EXISTS oauth_clients (issuer TEXT, redirect_uri TEXT, client_id TEXT, client_secret TEXT,
  PRIMARY KEY (issuer, redirect_uri));
CREATE TABLE IF NOT EXISTS oauth_states (state TEXT PRIMARY KEY, user TEXT, verifier TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS oauth_tokens (user TEXT PRIMARY KEY, data BLOB, updated_at REAL);
CREATE TABLE IF NOT EXISTS google_states (state TEXT PRIMARY KEY, user TEXT, verifier TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS google_tokens (user TEXT PRIMARY KEY, data BLOB, updated_at REAL);
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


def new_conversation(model: str, user: str) -> dict:
    conv = {"id": uuid.uuid4().hex[:12], "title": "New chat", "model": model, "created_at": time.time(), "user": user}
    with connect() as c:
        c.execute("INSERT INTO conversations VALUES (:id, :title, :model, :created_at, :user)", conv)
    return conv


def list_conversations(user: str) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM conversations WHERE user = ? ORDER BY created_at DESC LIMIT 200", (user,))]


def get_conversation(conv_id: str, user: str) -> dict | None:
    """Only the owner's: conversations hold CRM data the asker was allowed to see, not necessarily anyone else."""
    with connect() as c:
        row = c.execute("SELECT * FROM conversations WHERE id = ? AND user = ?", (conv_id, user)).fetchone()
        if not row:
            return None
        msgs = [json.loads(r[0]) for r in c.execute("SELECT message FROM messages WHERE conv_id = ? ORDER BY ix", (conv_id,))]
        runs = [_run(r) for r in c.execute("SELECT * FROM runs WHERE conv_id = ? ORDER BY id", (conv_id,))]
    return {**dict(row), "messages": msgs, "runs": runs}


def delete_conversation(conv_id: str, user: str) -> None:
    with connect() as c:
        if not c.execute("SELECT 1 FROM conversations WHERE id = ? AND user = ?", (conv_id, user)).fetchone():
            return
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


RUN_LIST_FIELDS = ["id", "created_at", "conv_id", "model", "question", "latency_ms", "prompt_tokens", "cache_hit_tokens",
                   "completion_tokens", "cost_usd", "tool_calls", "skills_loaded", "error"]


def list_runs(user: str, limit: int = 200) -> list[dict]:
    """Newest first, this user's only, without the full trace (it can be large)."""
    with connect() as c:
        rows = c.execute("SELECT * FROM runs WHERE conv_id IN (SELECT id FROM conversations WHERE user = ?) "
                         "ORDER BY id DESC LIMIT ?", (user, max(1, min(limit, 500)))).fetchall()
    return [{k: v for k, v in _run(r).items() if k in RUN_LIST_FIELDS} for r in rows]


CSV_FIELDS = ["id", "created_at", "conv_id", "model", "question", "latency_ms", "prompt_tokens", "cache_hit_tokens",
              "completion_tokens", "cost_usd", "tool_calls", "skills_loaded", "error", "user_email"]


def runs_csv(user: str) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    with connect() as c:
        for r in c.execute("SELECT * FROM runs WHERE conv_id IN (SELECT id FROM conversations WHERE user = ?) ORDER BY id", (user,)):
            row = dict(r)
            row["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(row["created_at"]))
            w.writerow(row)
    return out.getvalue()


# ---- OAuth (Pipedrive MCP) ----
def get_oauth_client(issuer: str, redirect_uri: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT client_id, client_secret FROM oauth_clients WHERE issuer = ? AND redirect_uri = ?", (issuer, redirect_uri)).fetchone()
    return dict(r) if r else None


def save_oauth_client(issuer: str, redirect_uri: str, reg: dict) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO oauth_clients VALUES (?, ?, ?, ?)", (issuer, redirect_uri, reg["client_id"], reg.get("client_secret")))


def save_oauth_state(state: str, user: str, verifier: str, created_at: float) -> None:
    with connect() as c:
        c.execute("DELETE FROM oauth_states WHERE created_at < ?", (created_at - 3600,))
        c.execute("INSERT INTO oauth_states VALUES (?, ?, ?, ?)", (state, user, verifier, created_at))


def pop_oauth_state(state: str) -> dict | None:
    """One use only: the state is deleted as it's read."""
    with connect() as c:
        r = c.execute("SELECT user, verifier, created_at FROM oauth_states WHERE state = ?", (state,)).fetchone()
        c.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    return dict(r) if r else None


def get_oauth_token(user: str) -> bytes | None:
    with connect() as c:
        r = c.execute("SELECT data FROM oauth_tokens WHERE user = ?", (user,)).fetchone()
    return r[0] if r else None


def save_oauth_token(user: str, blob: bytes) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO oauth_tokens VALUES (?, ?, ?)", (user, blob, time.time()))


def delete_oauth_token(user: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM oauth_tokens WHERE user = ?", (user,))


# ---- OAuth (Google) ----
def save_google_state(state: str, user: str, verifier: str, created_at: float) -> None:
    with connect() as c:
        c.execute("DELETE FROM google_states WHERE created_at < ?", (created_at - 3600,))
        c.execute("INSERT INTO google_states VALUES (?, ?, ?, ?)", (state, user, verifier, created_at))


def pop_google_state(state: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT user, verifier, created_at FROM google_states WHERE state = ?", (state,)).fetchone()
        c.execute("DELETE FROM google_states WHERE state = ?", (state,))
    return dict(r) if r else None


def get_google_token(user: str) -> bytes | None:
    with connect() as c:
        r = c.execute("SELECT data FROM google_tokens WHERE user = ?", (user,)).fetchone()
    return r[0] if r else None


def save_google_token(user: str, blob: bytes) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO google_tokens VALUES (?, ?, ?)", (user, blob, time.time()))


def delete_google_token(user: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM google_tokens WHERE user = ?", (user,))
