import asyncio
import json

import httpx
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from app import agent, config, main, oauth, skills
from app.pipedrive_mcp import PipedriveMCP
from app.tools import Toolbox
from fakes import FakeDeepSeek, fake_pipedrive_server, fake_session_opener, text_reply, tool_call_reply


def collect(ds, history, calls=None, with_pipedrive=True):
    calls = [] if calls is None else calls

    async def go():
        new, events = [], []
        async with httpx.AsyncClient(transport=ds.transport()) as client, \
                create_connected_server_and_client_session(fake_pipedrive_server(calls)) as session:
            pd = await PipedriveMCP.create(session) if with_pipedrive else None
            async for ev in agent.run_turn(client, Toolbox(skills.discover(), pd), "deepseek-flash", history, new):
                events.append(ev)
        return new, events
    return asyncio.run(go())


def test_a_turn_loads_a_skill_reads_pipedrive_then_answers():
    calls = []
    ds = FakeDeepSeek(tool_call_reply("load_skill", json.dumps({"name": "commercial-criteria"})),
                      tool_call_reply("pipedrive__search_deals", json.dumps({"term": "Playbill"}), "call_2"),
                      text_reply("Deal 4767 is Won at stage 58."))
    new, events = collect(ds, [{"role": "user", "content": "How is Playbill?"}], calls)
    kinds = [e["type"] for e in events]
    assert kinds.count("tool_start") == 2 and kinds.count("tool_end") == 2 and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Deal 4767 is Won at stage 58."
    done = events[-1]
    assert done["skills_loaded"] == ["commercial-criteria"]
    assert done["usage"] == {"prompt_tokens": 3500, "prompt_cache_hit_tokens": 2600, "completion_tokens": 90}
    assert done["cost_usd"] == round((2600 * 0.1 + 900 * 1.0 + 90 * 2.0) / 1e6, 6)
    assert calls == [("search_deals", "Playbill")]
    # the skill text went back as the tool result; arguments were reassembled from the stream
    assert "Komosion commercial assessment" in ds.requests[1]["messages"][-1]["content"]
    assert ds.requests[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == '{"name": "commercial-criteria"}'
    # DeepSeek was never even offered a write tool
    offered = {t["function"]["name"] for t in ds.requests[0]["tools"]}
    assert "pipedrive__search_deals" in offered and not offered & {"pipedrive__create_deal", "pipedrive__updateDeal"}
    assert "user's own Pipedrive account" in ds.requests[0]["messages"][0]["content"]
    assert [m["role"] for m in new] == ["assistant", "tool", "assistant", "tool", "assistant"]
    assert all("reasoning_content" not in m for m in new)   # thinking is shown, never sent back


def test_a_write_call_is_refused_and_never_reaches_pipedrive():
    calls = []
    ds = FakeDeepSeek(tool_call_reply("pipedrive__create_deal", '{"title": "Fake deal"}'), text_reply("I can't create deals."))
    _, events = collect(ds, [{"role": "user", "content": "Create a deal"}], calls)
    end = next(e for e in events if e["type"] == "tool_end")
    assert end["ok"] is False and "not an allowed read-only" in end["result"]
    assert calls == []


def test_without_pipedrive_only_load_skill_is_offered_and_the_prompt_says_so():
    ds = FakeDeepSeek(text_reply("Please connect Pipedrive."))
    collect(ds, [{"role": "user", "content": "How is Playbill?"}], with_pipedrive=False)
    assert [t["function"]["name"] for t in ds.requests[0]["tools"]] == ["load_skill"]
    assert "hasn't connected Pipedrive" in ds.requests[0]["messages"][0]["content"]


def test_unfinished_tool_calls_are_not_stored():
    ok = [{"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]}, {"role": "tool", "tool_call_id": "a", "content": "{}"}]
    assert main._complete(ok) == ok
    assert main._complete([*ok, {"role": "assistant", "content": "", "tool_calls": [{"id": "b"}, {"id": "c"}]},
                           {"role": "tool", "tool_call_id": "b", "content": "{}"}]) == ok


def test_api_streams_a_turn_with_the_users_pipedrive_and_keeps_chats_private(monkeypatch):
    calls, tokens = [], []
    ds = FakeDeepSeek(tool_call_reply("pipedrive__search_deals", '{"term": "Playbill"}'), text_reply("Deal 4767 is Won."))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    monkeypatch.setattr(main, "open_pipedrive_session", fake_session_opener(calls, tokens))

    async def cred_for(user):
        return {"kind": "oauth", "token": f"token-of-{user}", "transport": "mcp"}
    monkeypatch.setattr(oauth, "credential", cred_for)
    c = TestClient(main.app)
    me, other = {"cf-access-authenticated-user-email": "yethu@komosion.com"}, {"cf-access-authenticated-user-email": "linn@komosion.com"}
    conv = c.post("/api/conversations", json={}, headers=me).json()
    r = c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "How is Playbill?"}, headers=me)
    events = [json.loads(line[5:]) for line in r.text.split("\n\n") if line.startswith("data:")]
    assert events[0]["type"] == "pipedrive" and "pipedrive__search_deals" in events[0]["tools"] and "create_deal" in events[0]["blocked"]
    assert events[-1]["type"] == "done"
    assert tokens == ["token-of-yethu@komosion.com"] and calls == [("search_deals", "Playbill")]
    saved = c.get(f"/api/conversations/{conv['id']}", headers=me).json()
    assert saved["title"] == "How is Playbill?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert saved["runs"][0]["tool_calls"] == 1 and saved["runs"][0]["user_email"] == "yethu@komosion.com"
    # another user can't see, list, export or post to it
    assert c.get(f"/api/conversations/{conv['id']}", headers=other).status_code == 404
    assert c.get("/api/conversations", headers=other).json() == []
    assert "How is Playbill?" not in c.get("/api/runs.csv", headers=other).text
    assert "How is Playbill?" in c.get("/api/runs.csv", headers=me).text
    assert c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "x"}, headers=other).status_code == 404
    assert c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "x", "model": "gpt-4"}, headers=me).status_code == 422


def test_a_broken_pipedrive_connection_still_gets_an_answer(monkeypatch):
    ds = FakeDeepSeek(text_reply("Answering without CRM data."))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))

    async def cred_for(user):
        return {"kind": "oauth", "token": "t", "transport": "mcp"}

    def broken(token, kind="oauth"):
        raise ConnectionError("mcp.pipedrive.ai unreachable")
    monkeypatch.setattr(oauth, "credential", cred_for)
    monkeypatch.setattr(main, "open_pipedrive_session", broken)
    c = TestClient(main.app)
    conv = c.post("/api/conversations", json={}).json()
    events = [json.loads(line[5:]) for line in c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "hi"}).text.split("\n\n") if line.startswith("data:")]
    assert events[0]["type"] == "warning" and "unreachable" in events[0]["message"]
    assert events[-1]["type"] == "done"


def test_the_browser_never_receives_a_secret(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-secret-123")
    monkeypatch.setattr(config, "SECRET_KEY", "enc-secret-456")
    body = TestClient(main.app).get("/api/config").text
    assert "secret" not in body


def test_deepseek_is_told_the_current_time_without_touching_the_cache_prefix_or_the_stored_chat():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    hist = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "What's next?"}]
    sent = agent.with_now(hist, datetime(2026, 11, 1, 9, 5, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")))
    assert sent[-1]["content"] == "[Current date and time: Sunday 01 November 2026, 09:05 (Asia/Ho_Chi_Minh, UTC+07:00)]\nWhat's next?"
    assert sent[:-1] == hist[:-1] and hist[-1]["content"] == "What's next?"   # earlier turns and the original untouched
    ds = FakeDeepSeek(text_reply("Monday."))
    new, _ = collect(ds, [{"role": "user", "content": "What's next?"}], with_pipedrive=False)
    assert ds.requests[0]["messages"][-1]["content"].startswith("[Current date and time: ")
    assert "Current date and time" not in ds.requests[0]["messages"][0]["content"]   # system prompt stays cacheable
