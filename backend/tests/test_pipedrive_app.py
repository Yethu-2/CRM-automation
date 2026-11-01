import asyncio
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, main, oauth, store
from app.pipedrive_rest import PipedriveREST
from fakes import FakeDeepSeek, FakePipedriveREST, text_reply, tool_call_reply

H = {"cf-access-authenticated-user-email": "yethu@komosion.com"}
API_DOMAIN = "https://komosion-sandbox.pipedrive.com"


class FakeAppOAuth:
    """oauth.pipedrive.com for a Developer Hub app: Basic auth with the app's client, returns api_domain."""
    def __init__(self):
        self.issued, self.forms = 0, []

    def transport(self):
        def handle(req: httpx.Request):
            assert str(req.url) == oauth.APP_TOKEN_URL
            assert req.headers["authorization"].startswith("Basic ")
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            self.forms.append(form)
            assert "resource" not in form                         # None values are never sent
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"app-access-{self.issued}", "refresh_token": "app-refresh",
                                             "expires_in": 3599, "api_domain": API_DOMAIN, "scope": "deals:read contacts:read"})
        return httpx.MockTransport(handle)


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    for k, v in {"DATA_DIR": tmp_path, "DB_PATH": tmp_path / "crm.db", "SECRET_KEY": "s", "BASE_URL": "https://crm.example",
                 "PIPEDRIVE_APP_CLIENT_ID": "app-cid", "PIPEDRIVE_APP_CLIENT_SECRET": "app-secret"}.items():
        monkeypatch.setattr(config, k, v)
    auth, rest = FakeAppOAuth(), FakePipedriveREST()
    monkeypatch.setattr(oauth, "make_http_client", lambda: httpx.AsyncClient(transport=auth.transport()))
    bases = []

    def make_rest(token, base_url=None, bearer=False):
        bases.append((base_url, bearer))
        return PipedriveREST(token, base_url=base_url, bearer=bearer, transport=rest.transport())
    monkeypatch.setattr(main, "make_pipedrive_rest", make_rest)

    @asynccontextmanager
    async def mcp_refuses(token, kind="oauth"):
        raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://mcp"), response=httpx.Response(401))
        yield
    monkeypatch.setattr(main, "open_pipedrive_session", mcp_refuses)
    return auth, rest, bases


def sign_in(c):
    r = c.get("/oauth/pipedrive/start", headers=H, follow_redirects=False)
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return r, q, c.get("/oauth/callback", params={"code": "the-code", "state": q["state"][0]}, headers=H, follow_redirects=False)


def test_app_sign_in_uses_the_app_client_and_falls_back_to_rest_at_the_company_domain(app_env):
    auth, rest, bases = app_env
    c = TestClient(main.app)
    start, q, cb = sign_in(c)
    assert start.headers["location"].startswith(oauth.APP_AUTHORIZE_URL + "?")
    assert q["client_id"] == ["app-cid"] and q["redirect_uri"] == ["https://crm.example/oauth/callback"]
    assert cb.status_code == 302 and cb.headers["location"] == "/?pipedrive=connected"
    assert auth.forms[0]["grant_type"] == "authorization_code" and auth.forms[0]["redirect_uri"] == "https://crm.example/oauth/callback"
    st = c.get("/api/config", headers=H).json()["pipedrive"]
    assert st["connected"] and st["kind"] == "app" and st["transport"] == "rest" and st["account"]["company"] == "Komosion Sandbox"
    assert bases[0] == (API_DOMAIN, True)
    assert rest.requests[0].url.host == "komosion-sandbox.pipedrive.com" and rest.requests[0].headers["authorization"] == "Bearer app-access-1"
    blob = store.get_oauth_token("yethu@komosion.com")
    assert b"app-access-1" not in blob and b"app-secret" not in blob


def test_chat_and_refresh_keep_the_company_domain(app_env, monkeypatch):
    auth, rest, bases = app_env
    c = TestClient(main.app)
    sign_in(c)
    later = time.time() + 7200
    monkeypatch.setattr(oauth.time, "time", lambda: later)                # token expired: refreshed on the next chat
    ds = FakeDeepSeek(tool_call_reply("pipedrive_search", '{"entity": "deals", "term": "Sandbox"}'), text_reply("Deal 7."))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    conv = c.post("/api/conversations", json={}, headers=H).json()
    raw = c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "Deals?"}, headers=H).text
    events = [json.loads(x[5:]) for x in raw.split("\n\n") if x.startswith("data:")]
    assert events[-1]["type"] == "done" and events[-1]["tools"][0]["ok"] is True
    assert auth.forms[-1]["grant_type"] == "refresh_token"
    assert bases[-1] == (API_DOMAIN, True)
    search = [r for r in rest.requests if r.url.path == "/api/v2/deals/search"][0]
    assert search.headers["authorization"] == "Bearer app-access-2" and search.method == "GET"
    cred = asyncio.run(oauth.credential("yethu@komosion.com"))
    assert cred["api_domain"] == API_DOMAIN and cred["transport"] == "rest"
