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
CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, user TEXT, title TEXT, held_at TEXT, client_name TEXT,
  client_org_id INTEGER, transcript TEXT, source TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, user TEXT, meeting_id TEXT, revision INTEGER, status TEXT,
  summary TEXT, changes TEXT, raw TEXT, feedback TEXT, decision_note TEXT, kept TEXT, model TEXT, cost_usd REAL,
  latency_ms INTEGER, tool_calls INTEGER, error TEXT, created_at REAL, reviewed_at REAL);
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


# ---- meetings and trigger proposals (per user) ----
def add_meeting(user: str, m: dict) -> dict:
    row = {"id": uuid.uuid4().hex[:12], "user": user, "title": m["title"], "held_at": m.get("held_at") or "",
           "client_name": (m.get("client_name") or "").strip(), "client_org_id": m.get("client_org_id"),
           "transcript": m["transcript"], "source": m.get("source") or "pasted", "created_at": time.time()}
    with connect() as c:
        c.execute("INSERT INTO meetings VALUES (:id, :user, :title, :held_at, :client_name, :client_org_id, :transcript, "
                  ":source, :created_at)", row)
    return row


def list_meetings(user: str) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM meetings WHERE user = ? ORDER BY held_at DESC, created_at DESC", (user,))]


def get_meeting(meeting_id: str, user: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM meetings WHERE id = ? AND user = ?", (meeting_id, user)).fetchone()
    return dict(r) if r else None


def delete_meeting(meeting_id: str, user: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM proposals WHERE meeting_id = ? AND user = ?", (meeting_id, user))
        c.execute("DELETE FROM meetings WHERE id = ? AND user = ?", (meeting_id, user))


def add_proposal(user: str, p: dict) -> dict:
    with connect() as c:
        rev = c.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM proposals WHERE meeting_id = ? AND user = ?",
                        (p["meeting_id"], user)).fetchone()[0]
        row = {"id": uuid.uuid4().hex[:12], "user": user, "meeting_id": p["meeting_id"], "revision": rev,
               "status": p["status"], "summary": p.get("summary") or "", "changes": json.dumps(p.get("changes") or [], ensure_ascii=False),
               "raw": p.get("raw") or "", "feedback": p.get("feedback") or "", "decision_note": "", "kept": "[]",
               "model": p.get("model"), "cost_usd": p.get("cost_usd"), "latency_ms": p.get("latency_ms"),
               "tool_calls": p.get("tool_calls") or 0, "error": p.get("error"), "created_at": time.time(), "reviewed_at": None}
        c.execute("INSERT INTO proposals VALUES (:id, :user, :meeting_id, :revision, :status, :summary, :changes, :raw, :feedback, "
                  ":decision_note, :kept, :model, :cost_usd, :latency_ms, :tool_calls, :error, :created_at, :reviewed_at)", row)
    return _proposal(row)


def list_proposals(user: str) -> list[dict]:
    with connect() as c:
        return [_proposal(dict(r)) for r in c.execute(
            "SELECT p.*, m.title AS meeting_title, m.client_name, m.client_org_id, m.held_at FROM proposals p "
            "JOIN meetings m ON m.id = p.meeting_id AND m.user = p.user WHERE p.user = ? ORDER BY p.created_at DESC", (user,))]


def get_proposal(proposal_id: str, user: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM proposals WHERE id = ? AND user = ?", (proposal_id, user)).fetchone()
    return _proposal(dict(r)) if r else None


def review_proposal(proposal_id: str, user: str, status: str, note: str = "", kept: list[int] | None = None) -> None:
    """Only a proposal that is still waiting for review can be decided; the drafted text is never overwritten."""
    with connect() as c:
        c.execute("UPDATE proposals SET status = ?, decision_note = ?, kept = ?, reviewed_at = ? "
                  "WHERE id = ? AND user = ? AND status = 'pending_review'",
                  (status, note, json.dumps(kept or []), time.time(), proposal_id, user))


def _proposal(d: dict) -> dict:
    d["changes"] = json.loads(d["changes"] or "[]") if isinstance(d.get("changes"), str) else d.get("changes") or []
    d["kept"] = json.loads(d["kept"] or "[]") if isinstance(d.get("kept"), str) else d.get("kept") or []
    return d


def dashboard_stats(user: str) -> dict:
    with connect() as c:
        runs = [dict(r) for r in c.execute("SELECT * FROM runs WHERE conv_id IN (SELECT id FROM conversations WHERE user = ?) "
                                           "ORDER BY id DESC", (user,))]
        convs = c.execute("SELECT COUNT(*) FROM conversations WHERE user = ?", (user,)).fetchone()[0]
    skills_used: dict[str, int] = {}
    tools_used: dict[str, int] = {}
    for r in runs:
        for s in json.loads(r["skills_loaded"] or "[]"):
            skills_used[s] = skills_used.get(s, 0) + 1
        for t in json.loads(r["trace"] or "[]"):
            if t.get("name") != "load_skill":
                tools_used[t["name"]] = tools_used.get(t["name"], 0) + 1
    lat = [r["latency_ms"] for r in runs if r["latency_ms"]]
    recent = [{k: r[k] for k in ("id", "conv_id", "created_at", "model", "question", "latency_ms", "cost_usd", "tool_calls", "error")}
              for r in runs[:15]]
    return {"conversations": convs, "runs": len(runs), "errors": sum(1 for r in runs if r["error"]),
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in runs), "cache_hit_tokens": sum(r["cache_hit_tokens"] or 0 for r in runs),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in runs),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in runs), 6), "avg_latency_ms": int(sum(lat) / len(lat)) if lat else None,
            "skills_used": dict(sorted(skills_used.items(), key=lambda x: -x[1])),
            "tools_used": dict(sorted(tools_used.items(), key=lambda x: -x[1])), "recent_runs": recent}
