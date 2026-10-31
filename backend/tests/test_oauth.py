import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, main, oauth, store
from fakes import FakeAuthServer


@pytest.fixture
def auth(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(config, "BASE_URL", "https://crm.example")
    monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
    srv = FakeAuthServer()
    monkeypatch.setattr(oauth, "make_http_client", lambda: httpx.AsyncClient(transport=srv.transport()))
    return srv


def connect(srv, user="a@komosion.com"):
    url = asyncio.run(oauth.start(user))
    q = parse_qs(urlsplit(url).query)
    asyncio.run(oauth.finish(user, srv.authorize(q), q["state"][0]))
    return q


def test_start_discovers_registers_once_and_uses_pkce(auth):
    q = parse_qs(urlsplit(asyncio.run(oauth.start("a@komosion.com"))).query)
    assert q["client_id"] == ["cid-123"] and q["redirect_uri"] == ["https://crm.example/oauth/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["resource"] == [FakeAuthServer.MCP] 
    assert q["scope"] == ["base deals:full contacts:full activities:full search:read users:read"]   # never admin or mail-sending
    asyncio.run(oauth.start("b@komosion.com"))
    assert auth.registrations == 1


def test_connect_stores_an_encrypted_token_per_user(auth):
    connect(auth)
    assert asyncio.run(oauth.access_token("a@komosion.com")) == "access-1"
    assert asyncio.run(oauth.access_token("b@komosion.com")) is None
    blob = store.get_oauth_token("a@komosion.com")
    assert b"access-1" not in blob and b"csecret" not in blob
    oauth.disconnect("a@komosion.com")
    assert not oauth.connected("a@komosion.com")


def test_a_sign_in_link_works_once_and_only_for_whoever_started_it(auth):
    url = asyncio.run(oauth.start("a@komosion.com"))
    q = parse_qs(urlsplit(url).query)
    code = auth.authorize(q)
    with pytest.raises(oauth.OAuthError):
        asyncio.run(oauth.finish("mallory@example.com", code, q["state"][0]))
    with pytest.raises(oauth.OAuthError):   # the state was spent by the failed attempt
        asyncio.run(oauth.finish("a@komosion.com", code, q["state"][0]))


def test_expired_tokens_are_refreshed_and_a_refused_refresh_disconnects(auth, monkeypatch):
    connect(auth)
    later = time.time() + 7200
    monkeypatch.setattr(oauth.time, "time", lambda: later)
    assert asyncio.run(oauth.access_token("a@komosion.com")) == "access-2"
    monkeypatch.setattr(oauth.time, "time", lambda: later + 7200)
    auth.refresh_ok = False
    assert asyncio.run(oauth.access_token("a@komosion.com")) is None
    assert not oauth.connected("a@komosion.com")


def test_http_routes_and_access_requirement(auth, monkeypatch):
    c = TestClient(main.app, follow_redirects=False)
    h = {"cf-access-authenticated-user-email": "A@Komosion.com"}
    r = c.get("/oauth/pipedrive/start", headers=h)
    assert r.status_code == 302 and r.headers["location"].startswith(f"{FakeAuthServer.AS}/authorize?")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    r = c.get("/oauth/callback", params={"code": auth.authorize(q), "state": q["state"][0]}, headers=h)
    assert r.status_code == 302 and r.headers["location"] == "/?pipedrive=connected"
    assert c.get("/api/config", headers=h).json()["pipedrive"] == {"available": True, "connected": True}
    assert c.get("/oauth/callback", params={"error": "access_denied"}, headers=h).status_code == 400
    monkeypatch.setattr(config, "REQUIRE_ACCESS_EMAIL", True)
    assert c.get("/api/config").status_code == 401
    assert c.get("/api/health").status_code == 200
