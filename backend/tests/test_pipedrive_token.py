import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, main, oauth, store
from app.pipedrive_rest import PipedriveREST, ReadOnlyViolation
from fakes import FakeDeepSeek, FakePipedriveREST, fake_session_opener, text_reply, tool_call_reply

H = {"cf-access-authenticated-user-email": "yethu@komosion.com"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(config, "SECRET_KEY", "s")
    monkeypatch.setattr(config, "BASE_URL", "")   # no OAuth needed for tokens
    rest = FakePipedriveREST()
    monkeypatch.setattr(main, "make_pipedrive_rest", lambda token, base_url=None, bearer=False: PipedriveREST(token, base_url=base_url, bearer=bearer, transport=rest.transport()))
    return rest


def test_the_rest_client_cannot_write():
    for name in ("post", "put", "patch", "delete", "request", "send"):
        assert not hasattr(PipedriveREST, name), name
    rest = FakePipedriveREST()
    pd = PipedriveREST("sandbox-token-123", transport=rest.transport())
    for path in ("/v1/deals/1/followers", "/api/v2/deals/1/products", "/v1/users", "/api/v2/deals/../users"):
        with pytest.raises(ReadOnlyViolation):
            asyncio.run(pd.get(path))
    text, ok = asyncio.run(pd.call("pipedrive_search", {"entity": "deals", "term": "Sandbox"}))
    assert ok and "Sandbox deal" in text
    assert {r.method for r in rest.requests} == {"GET"} and "api_token" not in str(rest.requests[0].url)


def test_a_token_the_mcp_server_takes_connects_through_mcp(env, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "open_pipedrive_session", fake_session_opener([], seen))
    r = TestClient(main.app).post("/api/pipedrive/token", json={"token": "sandbox-token-123"}, headers=H)
    assert r.status_code == 200 and r.json()["transport"] == "mcp" and r.json()["account"]["company"] == "Komosion Sandbox"
    assert seen == ["api_token:sandbox-token-123"]
    st = TestClient(main.app).get("/api/config", headers=H).json()["pipedrive"]
    assert st["connected"] and st["kind"] == "api_token" and st["transport"] == "mcp" and st["available"] is False
    assert b"sandbox-token-123" not in store.get_oauth_token("yethu@komosion.com")
    assert "sandbox-token-123" not in json.dumps(st)


def test_a_token_the_mcp_server_refuses_falls_back_to_rest_and_bad_tokens_are_refused(env, monkeypatch):
    @asynccontextmanager
    async def refuse(token, kind="oauth"):
        raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://mcp"), response=httpx.Response(401))
        yield
    monkeypatch.setattr(main, "open_pipedrive_session", refuse)
    c = TestClient(main.app)
    assert c.post("/api/pipedrive/token", json={"token": "wrong-token-xyz"}, headers=H).status_code == 400
    r = c.post("/api/pipedrive/token", json={"token": "sandbox-token-123"}, headers=H)
    assert r.status_code == 200 and r.json()["transport"] == "rest"
    cred = asyncio.run(oauth.credential("yethu@komosion.com"))
    assert cred == {"kind": "api_token", "token": "sandbox-token-123", "transport": "rest", "account": r.json()["account"]}


def test_chat_uses_the_rest_tools_for_a_rest_connection(env, monkeypatch):
    def no_mcp(*a, **k):
        raise AssertionError("MCP must not be used for a REST connection")
    monkeypatch.setattr(main, "open_pipedrive_session", no_mcp)
    oauth.save_api_token("yethu@komosion.com", "sandbox-token-123", "rest", {"company": "Komosion Sandbox"})
    ds = FakeDeepSeek(tool_call_reply("pipedrive_search", '{"entity": "deals", "term": "Sandbox"}'), text_reply("Deal 7 is Sandbox deal."))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    c = TestClient(main.app)
    conv = c.post("/api/conversations", json={}, headers=H).json()
    raw = c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "Any deals?"}, headers=H).text
    events = [json.loads(x[5:]) for x in raw.split("\n\n") if x.startswith("data:")]
    assert events[0]["type"] == "pipedrive" and "pipedrive_search" in events[0]["tools"]
    assert events[-1]["type"] == "done" and events[-1]["tools"][0]["ok"] is True
    assert {t["function"]["name"] for t in ds.requests[0]["tools"]} >= {"pipedrive_search", "pipedrive_get", "pipedrive_notes"}
    assert any(r.url.path == "/api/v2/deals/search" for r in env.requests)
