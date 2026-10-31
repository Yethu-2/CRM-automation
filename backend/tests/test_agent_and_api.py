import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from app import agent, config, main, skills
from app.pipedrive import Pipedrive
from app.tools import Toolbox
from fakes import FakeDeepSeek, FakePipedrive, text_reply, tool_call_reply


def collect(ds, pd_fake, history):
    async def go():
        new, events = [], []
        async with httpx.AsyncClient(transport=ds.transport()) as client:
            tb = Toolbox(skills.discover(), Pipedrive(token="t", transport=pd_fake.transport()))
            async for ev in agent.run_turn(client, tb, "deepseek-flash", history, new):
                events.append(ev)
        return new, events
    return asyncio.run(go())


def test_a_turn_loads_a_skill_calls_pipedrive_then_answers():
    ds = FakeDeepSeek(tool_call_reply("load_skill", json.dumps({"name": "commercial-criteria"})),
                      tool_call_reply("pipedrive_search", json.dumps({"entity": "organizations", "term": "RMIT"}), "call_2"),
                      text_reply("RMIT is Org 2246."))
    new, events = collect(ds, FakePipedrive(), [{"role": "user", "content": "Tell me about RMIT"}])
    kinds = [e["type"] for e in events]
    assert kinds.count("tool_start") == 2 and kinds.count("tool_end") == 2 and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "RMIT is Org 2246."
    done = events[-1]
    assert done["skills_loaded"] == ["commercial-criteria"]
    assert done["usage"] == {"prompt_tokens": 3500, "prompt_cache_hit_tokens": 2600, "completion_tokens": 90}
    assert done["cost_usd"] == round((2600 * 0.1 + 900 * 1.0 + 90 * 2.0) / 1e6, 6)
    # the skill text went back to the model as the tool result; the arguments were reassembled from the stream
    assert "Komosion commercial assessment" in ds.requests[1]["messages"][-1]["content"]
    assert ds.requests[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == '{"name": "commercial-criteria"}'
    assert [m["role"] for m in new] == ["assistant", "tool", "assistant", "tool", "assistant"]
    assert all("reasoning_content" not in m for m in new)   # thinking is shown, never sent back


def test_tool_errors_go_back_to_the_model_instead_of_crashing():
    ds = FakeDeepSeek(tool_call_reply("pipedrive_get", '{"entity": "users", "id": 1}'), text_reply("Sorry, I can't."))
    new, events = collect(ds, FakePipedrive(), [{"role": "user", "content": "x"}])
    end = next(e for e in events if e["type"] == "tool_end")
    assert end["ok"] is False and "entity must be one of" in end["result"]
    assert events[-1]["type"] == "done"


def test_no_pipedrive_token_means_only_load_skill_is_offered():
    tb = Toolbox(skills.discover(), Pipedrive(token=""))
    assert [t["function"]["name"] for t in tb.schemas()] == ["load_skill"]


def test_unfinished_tool_calls_are_not_stored():
    ok = [{"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]}, {"role": "tool", "tool_call_id": "a", "content": "{}"}]
    assert main._complete(ok) == ok
    assert main._complete([*ok, {"role": "assistant", "content": "", "tool_calls": [{"id": "b"}, {"id": "c"}]},
                           {"role": "tool", "tool_call_id": "b", "content": "{}"}]) == ok


def test_api_streams_a_turn_and_stores_messages_runs_and_csv(monkeypatch):
    ds = FakeDeepSeek(tool_call_reply("pipedrive_search", '{"entity": "deals", "term": "Playbill"}'), text_reply("Deal 4767 is Won."))
    pd = FakePipedrive()
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    monkeypatch.setattr(main, "make_pipedrive", lambda: Pipedrive(token="t", transport=pd.transport()))
    c = TestClient(main.app)
    assert c.get("/api/config").json()["skills"]
    conv = c.post("/api/conversations", json={}).json()
    r = c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "How is Playbill?"},
               headers={"cf-access-authenticated-user-email": "yethu@example.com"})
    events = [json.loads(line[5:]) for line in r.text.split("\n\n") if line.startswith("data:")]
    assert events[-1]["type"] == "done"
    saved = c.get(f"/api/conversations/{conv['id']}").json()
    assert saved["title"] == "How is Playbill?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert saved["runs"][0]["tool_calls"] == 1 and saved["runs"][0]["user_email"] == "yethu@example.com"
    csv_text = c.get("/api/runs.csv").text
    assert csv_text.splitlines()[0].startswith("id,created_at") and "How is Playbill?" in csv_text
    assert c.post(f"/api/conversations/{conv['id']}/messages", json={"text": "x", "model": "gpt-4"}).status_code == 422


def test_the_browser_never_receives_a_secret(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-secret-123")
    monkeypatch.setattr(config, "PIPEDRIVE_API_TOKEN", "pd-secret-456")
    body = TestClient(main.app).get("/api/config").text
    assert "secret" not in body and json.loads(body)["pipedrive_configured"] is True
