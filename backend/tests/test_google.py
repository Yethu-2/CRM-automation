import asyncio
import base64
import hashlib
import io
import json
import time
import zipfile
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, google_oauth, main, oauth, store
from app.google_tools import GoogleWorkspace, docx_text
from fakes import FakeDeepSeek, text_reply, tool_call_reply

RO = google_oauth.SCOPES


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeGoogleAuth:
    def __init__(self):
        self.challenges, self.revoked, self.issued = {}, [], 0
        # exactly what Google sends back: "email" comes back as userinfo.email, in its own order
        self.scope = ("https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/userinfo.email openid "
                      "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.readonly")
        self.refresh_ok = True

    def authorize(self, q):
        code = f"g-code-{len(self.challenges) + 1}"
        self.challenges[code] = q["code_challenge"][0]
        return code

    def transport(self):
        def handle(req: httpx.Request):
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            if str(req.url) == google_oauth.REVOKE_URL:
                self.revoked.append(form["token"])
                return httpx.Response(200)
            assert str(req.url) == google_oauth.TOKEN_URL and form["client_secret"] == "gsecret"
            if form["grant_type"] == "authorization_code":
                want = self.challenges.pop(form["code"], None)
                got = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if want != got:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.issued += 1
                id_token = "x." + b64(json.dumps({"email": "yethu@komosion.com"})) + ".y"
                return httpx.Response(200, json={"access_token": f"g-access-{self.issued}", "refresh_token": "g-refresh",
                                                 "expires_in": 3599, "scope": self.scope, "id_token": id_token})
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"g-access-{self.issued}", "expires_in": 3599, "scope": self.scope})
        return httpx.MockTransport(handle)


@pytest.fixture
def g(monkeypatch, tmp_path):
    for k, v in {"DATA_DIR": tmp_path, "DB_PATH": tmp_path / "crm.db", "BASE_URL": "https://crm.example", "SECRET_KEY": "s",
                 "GOOGLE_ENABLED": True, "GOOGLE_CLIENT_ID": "gid", "GOOGLE_CLIENT_SECRET": "gsecret"}.items():
        monkeypatch.setattr(config, k, v)
    fake = FakeGoogleAuth()
    monkeypatch.setattr(google_oauth, "make_http_client", lambda: httpx.AsyncClient(transport=fake.transport()))
    return fake


def connect(fake, user="yethu@komosion.com"):
    q = parse_qs(urlsplit(google_oauth.start(user)).query)
    asyncio.run(google_oauth.finish(user, fake.authorize(q), q["state"][0]))
    return q


def test_consent_asks_for_read_only_scopes_with_pkce_and_offline_access(g):
    q = parse_qs(urlsplit(google_oauth.start("yethu@komosion.com")).query)
    scopes = q["scope"][0].split()
    assert {s.rsplit("/", 1)[-1] for s in scopes if "googleapis" in s} == {"gmail.readonly", "drive.readonly", "calendar.readonly"}
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["https://crm.example/oauth/google/callback"] and q["login_hint"] == ["yethu@komosion.com"]


def test_connect_stores_encrypted_tokens_and_the_account(g):
    connect(g)
    assert asyncio.run(google_oauth.access_token("yethu@komosion.com")) == "g-access-1"
    assert google_oauth.status("yethu@komosion.com") == {"available": True, "connected": True, "account": "yethu@komosion.com"}
    blob = store.get_google_token("yethu@komosion.com")
    assert b"g-access-1" not in blob and b"g-refresh" not in blob
    assert asyncio.run(google_oauth.access_token("linn@komosion.com")) is None


def test_unticked_or_wider_scopes_are_refused(g):
    full = g.scope
    g.scope = full.replace("https://www.googleapis.com/auth/calendar.readonly ", "")   # calendar unticked on the consent screen
    with pytest.raises(oauth.OAuthError, match="calendar.readonly"):
        connect(g)
    g.scope = full + " https://www.googleapis.com/auth/gmail.send"
    with pytest.raises(oauth.OAuthError, match="more access than read-only"):
        connect(g)
    g.scope = full + " https://www.googleapis.com/auth/drive"                       # full Drive is not read-only either
    with pytest.raises(oauth.OAuthError, match="more access than read-only"):
        connect(g)
    assert not google_oauth.status("yethu@komosion.com")["connected"]


def test_state_is_single_use_and_bound_to_the_user(g):
    q = parse_qs(urlsplit(google_oauth.start("yethu@komosion.com")).query)
    code = g.authorize(q)
    with pytest.raises(oauth.OAuthError):
        asyncio.run(google_oauth.finish("mallory@example.com", code, q["state"][0]))
    with pytest.raises(oauth.OAuthError):
        asyncio.run(google_oauth.finish("yethu@komosion.com", code, q["state"][0]))


def test_refresh_keeps_the_refresh_token_and_a_lapsed_grant_disconnects(g, monkeypatch):
    connect(g)
    later = time.time() + 7200
    monkeypatch.setattr(google_oauth.time, "time", lambda: later)
    assert asyncio.run(google_oauth.access_token("yethu@komosion.com")) == "g-access-2"
    monkeypatch.setattr(google_oauth.time, "time", lambda: later + 7200)
    assert asyncio.run(google_oauth.access_token("yethu@komosion.com")) == "g-access-3"   # refresh token survived the first refresh
    monkeypatch.setattr(google_oauth.time, "time", lambda: later + 14400)
    g.refresh_ok = False
    assert asyncio.run(google_oauth.access_token("yethu@komosion.com")) is None
    assert not google_oauth.status("yethu@komosion.com")["connected"]


def test_disconnect_also_revokes_at_google(g):
    connect(g)
    asyncio.run(google_oauth.disconnect("yethu@komosion.com"))
    assert g.revoked == ["g-refresh"] and not google_oauth.status("yethu@komosion.com")["connected"]


def test_switched_off_means_no_connect_and_no_tokens(g, monkeypatch):
    connect(g)
    monkeypatch.setattr(config, "GOOGLE_ENABLED", False)
    assert google_oauth.status("yethu@komosion.com")["available"] is False
    assert asyncio.run(google_oauth.access_token("yethu@komosion.com")) is None
    with pytest.raises(oauth.OAuthError):
        google_oauth.start("yethu@komosion.com")


# ---- the tools ----
def docx(paragraphs):
    xml = "<w:document><w:body>" + "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs) + "</w:body></w:document>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class FakeGoogleAPIs:
    def __init__(self):
        self.requests = []

    def transport(self):
        def handle(req: httpx.Request):
            self.requests.append(req)
            p, q = req.url.path, dict(req.url.params)
            if p.endswith("/users/me/messages"):
                return httpx.Response(200, json={"messages": [{"id": "m1", "threadId": "t1"}]})
            if p.endswith("/users/me/messages/m1"):
                return httpx.Response(200, json={"threadId": "t1", "snippet": "Thanks &amp; see you", "payload": {"headers": [
                    {"name": "From", "value": "Sarah <sarah@playbill.com>"}, {"name": "Subject", "value": "ROM sprint"}]}})
            if p.endswith("/users/me/threads/t1"):
                return httpx.Response(200, json={"messages": [
                    {"payload": {"headers": [{"name": "From", "value": "a@x.com"}], "mimeType": "multipart/alternative", "parts": [
                        {"mimeType": "text/plain", "body": {"data": b64("Signed agreement attached.")}},
                        {"mimeType": "text/html", "body": {"data": b64("<p>ignored</p>")}}]}},
                    {"payload": {"headers": [], "mimeType": "text/html", "body": {"data": b64("<style>x{}</style><p>Only&nbsp;HTML</p>")}}}]})
            if p == "/drive/v3/files":
                return httpx.Response(200, json={"files": [{"id": "d1", "name": "Playbill proposal"}]})
            if p == "/drive/v3/files/d1":
                return httpx.Response(200, json={"id": "d1", "name": "Proposal", "mimeType": "application/vnd.google-apps.document"})
            if p == "/drive/v3/files/d1/export":
                return httpx.Response(200, text="Proposal text")
            if p == "/drive/v3/files/w1":
                if q.get("alt") == "media":
                    return httpx.Response(200, content=docx(["Handover", "Read-only &amp; safe"]))
                return httpx.Response(200, json={"id": "w1", "name": "h.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
            if p.endswith("/calendars/primary/events"):
                return httpx.Response(200, json={"items": [{"summary": "VTAC call", "start": {"dateTime": "2026-11-03T10:00:00+07:00"},
                                                            "end": {"date": "2026-11-03"}, "attendees": [{"email": "a@vtac.edu.au"}]}]})
            return httpx.Response(404, text=p)
        return httpx.MockTransport(handle)


def test_tools_read_gmail_drive_and_calendar_with_gets_only():
    apis = FakeGoogleAPIs()
    gw = GoogleWorkspace("tok", transport=apis.transport())

    async def go():
        out = [await gw.gmail_search("Playbill"), await gw.gmail_thread("t1"), await gw.drive_search("Playbill's proposal"),
               await gw.drive_read("d1"), await gw.drive_read("w1"), await gw.calendar("2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z")]
        with pytest.raises(ValueError):
            await gw.gmail_thread("../../profile")
        await gw.aclose()
        return out
    search, thread, files, doc, word, events = asyncio.run(go())
    assert search == [{"thread_id": "t1", "from": "Sarah <sarah@playbill.com>", "to": None, "subject": "ROM sprint", "date": None, "snippet": "Thanks & see you"}]
    assert thread["messages"][0]["text"] == "Signed agreement attached." and thread["messages"][1]["text"] == "Only\xa0HTML"
    assert files[0]["id"] == "d1" and "name contains 'Playbill\\'s proposal'" in dict(apis.requests[3].url.params)["q"]
    assert doc["text"] == "Proposal text" and word["text"] == "Handover\nRead-only & safe"
    assert events[0]["summary"] == "VTAC call" and events[0]["attendees"] == ["a@vtac.edu.au"]
    assert {r.method for r in apis.requests} == {"GET"} and all(r.headers["authorization"] == "Bearer tok" for r in apis.requests)


def test_docx_text():
    assert docx_text(docx(["One", "Two"])) == "One\nTwo"


def test_chat_offers_google_tools_only_to_a_connected_user(g, monkeypatch):
    apis = FakeGoogleAPIs()
    connect(g)
    ds = FakeDeepSeek(tool_call_reply("google_gmail_search", '{"query": "Playbill"}'), text_reply("Sarah emailed about the ROM sprint."))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    monkeypatch.setattr(main, "make_google", lambda token: GoogleWorkspace(token, transport=apis.transport()))
    c = TestClient(main.app)
    h = {"cf-access-authenticated-user-email": "yethu@komosion.com"}
    conv = c.post("/api/conversations", json={}, headers=h).json()
    events = [json.loads(x[5:]) for x in c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "Any Playbill email?"}, headers=h).text.split("\n\n") if x.startswith("data:")]
    assert events[-1]["type"] == "done" and events[-1]["tools"][0]["ok"] is True
    offered = {t["function"]["name"] for t in ds.requests[0]["tools"]}
    assert {"google_gmail_search", "google_drive_read_file", "google_calendar_events"} <= offered
    assert "read the user's own email" in ds.requests[0]["messages"][0]["content"]
    assert apis.requests[0].headers["authorization"] == "Bearer g-access-1"
    assert c.get("/api/config", headers=h).json()["google"]["connected"] is True
    # someone else gets no Google tools
    ds2 = FakeDeepSeek(text_reply("No."))
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds2.transport()))
    other = {"cf-access-authenticated-user-email": "linn@komosion.com"}
    conv2 = c.post("/api/conversations", json={}, headers=other).json()
    c.post(f"/api/conversations/{conv2['id']}/messages", json={"text": "Any email?"}, headers=other)
    assert not any(t["function"]["name"].startswith("google_") for t in ds2.requests[0]["tools"])
