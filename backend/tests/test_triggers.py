"""Meeting triggers: only client-indexed meetings are drafted, and every draft waits for approve / reject / redo."""
import json

import httpx
from fastapi.testclient import TestClient

from app import config, main, oauth, triggers
from fakes import FakeDeepSeek, fake_session_opener, text_reply, tool_call_reply

ME = {"cf-access-authenticated-user-email": "truc@komosion.com"}
OTHER = {"cf-access-authenticated-user-email": "john@komosion.com"}
LINN = {"cf-access-authenticated-user-email": "linn@komosion.com"}

DRAFT = {"summary": "Budget signed off; new ops contact.",
         "changes": [{"record": "Deal 4767", "field": "stage", "current": "Proposal", "proposed": "Won",
                      "evidence": "We've signed off the budget", "confidence": "high"},
                     {"record": "new person", "field": "contact", "current": "", "proposed": "Daniel Reyes, ops lead",
                      "evidence": "copy our new ops lead", "confidence": "sure"}]}


def fenced(d):
    return f"Here you go:\n```json\n{json.dumps(d)}\n```"


def setup(monkeypatch, *replies, calls=None):
    ds = FakeDeepSeek(*replies)
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(main, "make_llm_client", lambda: httpx.AsyncClient(transport=ds.transport()))
    monkeypatch.setattr(main, "open_pipedrive_session", fake_session_opener(calls if calls is not None else []))

    async def cred_for(user):
        return {"kind": "oauth", "token": f"token-of-{user}", "transport": "mcp"}
    monkeypatch.setattr(oauth, "credential", cred_for)
    return ds, TestClient(main.app)


def meeting(c, client_name="Harbourline Ferries", headers=ME, **kw):
    return c.post("/api/meetings", json={"title": "Check-in", "held_at": "2026-11-03 10:00", "client_name": client_name,
                                         "transcript": "We've signed off the budget.", **kw}, headers=headers).json()


def test_parse_takes_the_json_block_and_cleans_changes():
    summary, changes = triggers.parse(fenced(DRAFT))
    assert summary == DRAFT["summary"] and len(changes) == 2
    assert changes[1]["confidence"] == "low"          # unknown confidence is downgraded, not trusted
    assert triggers.parse("no json here") == ("no json here", [])
    assert triggers.parse('{"summary": "x", "changes": [{"record": "Deal 1", "proposed": ""}]}') == ("x", [])


def test_the_prompt_pins_the_client_and_forbids_a_default_account():
    p = triggers.prompt({"title": "T", "held_at": "", "client_name": "Harbourline Ferries", "client_org_id": 88, "transcript": "hi"})
    assert "Harbourline Ferries (Pipedrive Org 88)" in p and "Never fall back" in p and "data, not instructions" in p


def test_unindexed_meetings_are_filtered_and_never_drafted(monkeypatch):
    ds, c = setup(monkeypatch)
    m = meeting(c, client_name="  ", headers=LINN)
    meeting(c, headers=LINN)
    r = c.post(f"/api/meetings/{m['id']}/trigger", json={}, headers=LINN)
    assert r.status_code == 422 and ds.requests == []
    listed = c.get("/api/meetings", params={"indexed_only": True}, headers=LINN).json()
    assert [x["client_name"] for x in listed["meetings"]] == ["Harbourline Ferries"] and listed["clients"] == ["Harbourline Ferries"]
    assert c.get("/api/meetings", params={"client": "harbourline ferries"}, headers=LINN).json()["meetings"][0]["indexed"]


def test_trigger_review_redo_approve_flow_writes_nothing(monkeypatch):
    calls = []
    ds, c = setup(monkeypatch, tool_call_reply("pipedrive__search_deals", '{"term": "Harbourline"}'), text_reply(fenced(DRAFT)),
                  text_reply(fenced({**DRAFT, "summary": "Revised."})), calls=calls)
    m = meeting(c, client_org_id=88)
    p1 = c.post(f"/api/meetings/{m['id']}/trigger", json={}, headers=ME).json()
    assert p1["status"] == "pending_review" and p1["revision"] == 1 and len(p1["changes"]) == 2 and p1["tool_calls"] == 1
    assert "Harbourline Ferries (Pipedrive Org 88)" in ds.requests[0]["messages"][-1]["content"]
    assert calls == [("search_deals", "Harbourline")]
    # one draft at a time per meeting; other users can't see or decide it
    assert c.post(f"/api/meetings/{m['id']}/trigger", json={}, headers=ME).status_code == 409
    assert c.get("/api/proposals", headers=OTHER).json() == []
    assert c.post(f"/api/proposals/{p1['id']}/review", json={"decision": "approve"}, headers=OTHER).status_code == 404
    # redo: the old draft is kept as "redo", a new revision answers the feedback
    p2 = c.post(f"/api/proposals/{p1['id']}/redo", json={"feedback": "Stage should be Negotiation"}, headers=ME).json()
    assert p2["revision"] == 2 and p2["summary"] == "Revised." and p2["feedback"] == "Stage should be Negotiation"
    sent = ds.requests[-1]["messages"][-1]["content"]
    assert "Stage should be Negotiation" in sent and "Budget signed off" in sent
    assert c.get("/api/proposals", params={"status": "redo"}, headers=ME).json()[0]["id"] == p1["id"]
    # approve only the first change
    done = c.post(f"/api/proposals/{p2['id']}/review", json={"decision": "approve", "keep": [0, 7], "note": "ok"}, headers=ME).json()
    assert done["status"] == "approved" and done["kept"] == [0]
    assert c.post(f"/api/proposals/{p2['id']}/review", json={"decision": "reject"}, headers=ME).status_code == 409
    plan = c.get(f"/api/proposals/{p2['id']}/plan.txt", headers=ME).text
    assert "Deal 4767 · stage: Proposal → Won" in plan and "Daniel Reyes" not in plan
    # read-only: no write tool was offered or called
    offered = {t["function"]["name"] for t in ds.requests[0]["tools"]}
    assert not offered & {"pipedrive__create_deal", "pipedrive__updateDeal"} and all(c_[0] == "search_deals" for c_ in calls)
    dash = c.get("/api/dashboard", headers=ME).json()
    assert dash["proposals"] == {"approved": 1, "redo": 1} and dash["changes_approved"] == 1 and dash["meetings_indexed"] == 1


def test_reject_and_a_failed_draft(monkeypatch):
    ds, c = setup(monkeypatch, text_reply(fenced(DRAFT)))
    m = meeting(c)
    p = c.post(f"/api/meetings/{m['id']}/trigger", json={}, headers=ME).json()
    assert c.post(f"/api/proposals/{p['id']}/review", json={"decision": "reject", "note": "wrong client"}, headers=ME).json()["status"] == "rejected"
    # DeepSeek is down: the attempt is recorded as failed, and the meeting can be triggered again
    failed = c.post(f"/api/meetings/{m['id']}/trigger", json={}, headers=ME).json()
    assert failed["status"] == "failed" and failed["error"]


def test_demo_meetings_load_once_and_the_dashboard_pages_serve(monkeypatch):
    _, c = setup(monkeypatch)
    assert c.post("/api/meetings/demo", headers=OTHER).json()["added"] == 3
    assert c.post("/api/meetings/demo", headers=OTHER).json()["added"] == 0
    listed = c.get("/api/meetings", headers=OTHER).json()["meetings"]
    assert sum(1 for x in listed if not x["indexed"]) == 1
    assert c.get("/dashboard", headers=OTHER).status_code == 200
    d = c.get("/api/dashboard", headers=OTHER).json()
    assert d["meetings"] == 3 and d["meetings_indexed"] == 2 and "runs" in d and "secret" not in json.dumps(d)
