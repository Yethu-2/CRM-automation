"""Read-only Gmail, Drive and Calendar tools for DeepSeek. Every request is a GET with the user's read-only token."""
from __future__ import annotations

import base64
import html
import io
import json
import re
import zipfile
from typing import Any

import httpx

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3/files"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MESSAGE_CHARS = 6000
FILE_CHARS = 20000

SCHEMAS = [
    {"type": "function", "function": {
        "name": "google_gmail_search",
        "description": "[Gmail, read-only] Search the user's email with Gmail search syntax (e.g. 'from:vtac.edu.au newer_than:30d', "
                       "'subject:proposal Playbill'). Returns sender, subject, date, snippet and thread IDs.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "description": "1-20, default 10"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "google_gmail_read_thread",
        "description": "[Gmail, read-only] Read every message in an email thread, as plain text.",
        "parameters": {"type": "object", "properties": {"thread_id": {"type": "string"}}, "required": ["thread_id"]}}},
    {"type": "function", "function": {
        "name": "google_drive_search",
        "description": "[Drive, read-only] Search the user's Google Drive (including shared drives) by file name and content.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "description": "1-20, default 10"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "google_drive_read_file",
        "description": "[Drive, read-only] Read a Drive file as text: Google Docs/Sheets/Slides, PDF, Word (.docx) and text files.",
        "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}}},
    {"type": "function", "function": {
        "name": "google_calendar_events",
        "description": "[Calendar, read-only] List events on the user's primary calendar between two dates (RFC 3339, e.g. "
                       "2026-11-01T00:00:00+07:00), optionally filtered by text.",
        "parameters": {"type": "object", "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"},
                                                        "query": {"type": "string"}}, "required": ["time_min", "time_max"]}}},
]
NAMES = {s["function"]["name"] for s in SCHEMAS}


class GoogleWorkspace:
    def __init__(self, access_token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(timeout=30, transport=transport, headers={"Authorization": f"Bearer {access_token}"})

    def schemas(self) -> list[dict]:
        return SCHEMAS

    def handles(self, name: str) -> bool:
        return name in NAMES

    async def call(self, name: str, a: dict[str, Any]) -> tuple[str, bool]:
        fn = {"google_gmail_search": lambda: self.gmail_search(a["query"], a.get("max_results", 10)),
              "google_gmail_read_thread": lambda: self.gmail_thread(a["thread_id"]),
              "google_drive_search": lambda: self.drive_search(a["query"], a.get("max_results", 10)),
              "google_drive_read_file": lambda: self.drive_read(a["file_id"]),
              "google_calendar_events": lambda: self.calendar(a["time_min"], a["time_max"], a.get("query"))}[name]
        result = await fn()
        return (result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, separators=(",", ":"))), True

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        r = await self._client.get(url, params={k: v for k, v in (params or {}).items() if v not in (None, "")})
        if r.status_code >= 400:
            raise RuntimeError(f"Google HTTP {r.status_code}: {r.text[:300]}")
        return r

    # ---- Gmail ----
    async def gmail_search(self, query: str, max_results: int = 10) -> list[dict]:
        ids = (await self._get(f"{GMAIL}/messages", {"q": query, "maxResults": _clamp(max_results, 20)})).json().get("messages", [])
        out = []
        for m in ids:
            d = (await self._get(f"{GMAIL}/messages/{m['id']}", {"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]})).json()
            h = {x["name"].lower(): x["value"] for x in d.get("payload", {}).get("headers", [])}
            out.append({"thread_id": d.get("threadId"), "from": h.get("from"), "to": h.get("to"), "subject": h.get("subject"),
                        "date": h.get("date"), "snippet": html.unescape(d.get("snippet", ""))})
        return out

    async def gmail_thread(self, thread_id: str) -> dict:
        d = (await self._get(f"{GMAIL}/threads/{_safe_id(thread_id)}", {"format": "full"})).json()
        msgs = []
        for m in d.get("messages", []):
            h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
            body = _body_text(m.get("payload", {})) or html.unescape(m.get("snippet", ""))
            msgs.append({"from": h.get("from"), "to": h.get("to"), "cc": h.get("cc"), "date": h.get("date"),
                         "subject": h.get("subject"), "text": body[:MESSAGE_CHARS]})
        return {"thread_id": thread_id, "messages": msgs}

    # ---- Drive ----
    async def drive_search(self, query: str, max_results: int = 10) -> list[dict]:
        q = query.replace("\\", "\\\\").replace("'", "\\'")
        r = await self._get(DRIVE, {"q": f"(name contains '{q}' or fullText contains '{q}') and trashed = false",
                                    "pageSize": _clamp(max_results, 20), "corpora": "allDrives", "includeItemsFromAllDrives": "true",
                                    "supportsAllDrives": "true", "orderBy": "modifiedTime desc",
                                    "fields": "files(id,name,mimeType,modifiedTime,owners(emailAddress),webViewLink)"})
        return r.json().get("files", [])

    async def drive_read(self, file_id: str) -> dict:
        fid = _safe_id(file_id)
        meta = (await self._get(f"{DRIVE}/{fid}", {"fields": "id,name,mimeType,modifiedTime,webViewLink", "supportsAllDrives": "true"})).json()
        mime = meta.get("mimeType", "")
        export = {"application/vnd.google-apps.document": "text/plain", "application/vnd.google-apps.presentation": "text/plain",
                  "application/vnd.google-apps.spreadsheet": "text/csv"}.get(mime)
        if export:
            text = (await self._get(f"{DRIVE}/{fid}/export", {"mimeType": export})).text
        elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
            text = (await self._get(f"{DRIVE}/{fid}", {"alt": "media", "supportsAllDrives": "true"})).text
        elif mime == "application/pdf":
            text = _pdf_text((await self._get(f"{DRIVE}/{fid}", {"alt": "media", "supportsAllDrives": "true"})).content)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = docx_text((await self._get(f"{DRIVE}/{fid}", {"alt": "media", "supportsAllDrives": "true"})).content)
        else:
            text = f"(can't read {mime} files as text)"
        truncated = len(text) > FILE_CHARS
        return {**meta, "text": text[:FILE_CHARS] + ("\n…[truncated]" if truncated else "")}

    # ---- Calendar ----
    async def calendar(self, time_min: str, time_max: str, query: str | None = None) -> list[dict]:
        r = await self._get(CALENDAR, {"timeMin": time_min, "timeMax": time_max, "q": query, "singleEvents": "true",
                                       "orderBy": "startTime", "maxResults": 50})
        return [{"summary": e.get("summary"), "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                 "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                 "attendees": [x.get("email") for x in e.get("attendees", [])][:30], "location": e.get("location"),
                 "description": (e.get("description") or "")[:1500]} for e in r.json().get("items", [])]

    async def aclose(self) -> None:
        await self._client.aclose()


def _clamp(n: Any, top: int) -> int:
    try:
        return min(max(int(n), 1), top)
    except (TypeError, ValueError):
        return 10


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value or ""):
        raise ValueError("invalid ID")
    return value


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _body_text(part: dict) -> str:
    """Prefer text/plain; fall back to text/html with tags stripped."""
    plain, rich = [], []

    def walk(p: dict) -> None:
        data = (p.get("body") or {}).get("data")
        if data and p.get("mimeType") == "text/plain":
            plain.append(_b64(data))
        elif data and p.get("mimeType") == "text/html":
            rich.append(_b64(data))
        for c in p.get("parts") or []:
            walk(c)
    walk(part)
    if plain:
        return "\n".join(plain).strip()
    return re.sub(r"\n\s*\n+", "\n\n", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", "\n".join(rich))))).strip()


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).strip()
