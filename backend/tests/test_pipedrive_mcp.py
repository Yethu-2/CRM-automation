import asyncio

from mcp.shared.memory import create_connected_server_and_client_session

from app.pipedrive_mcp import PipedriveMCP
from fakes import fake_pipedrive_server


def with_pipedrive(fn):
    calls = []

    async def go():
        async with create_connected_server_and_client_session(fake_pipedrive_server(calls)) as session:
            return await fn(await PipedriveMCP.create(session))
    return asyncio.run(go()), calls


def test_only_read_tools_are_offered():
    pd, _ = with_pipedrive(lambda pd: asyncio.sleep(0, pd))
    assert sorted(pd.read_tools) == ["pipedrive__deals_summary", "pipedrive__getPerson", "pipedrive__list_activities", "pipedrive__search_deals"]
    assert pd.blocked == ["create_deal", "get_and_lock", "search_and_update_deal", "updateDeal"]
    schemas = pd.schemas()
    assert {s["function"]["name"] for s in schemas} == set(pd.read_tools)
    assert all(s["function"]["description"].startswith("[Pipedrive, read-only]") for s in schemas)
    assert schemas[0]["function"]["parameters"]["type"] == "object"


def test_reads_go_through_and_writes_never_reach_the_server():
    async def go(pd):
        ok = await pd.call("pipedrive__search_deals", {"term": "Playbill"})
        blocked = await pd.call("pipedrive__create_deal", {"title": "x"})
        hidden = await pd.call("pipedrive__updateDeal", {"id": 1, "status": "won"})
        return ok, blocked, hidden
    (ok, blocked, hidden), calls = with_pipedrive(go)
    assert ok[1] is True and "Playbill ROM sprint" in ok[0]
    assert blocked[1] is False and hidden[1] is False and "not an allowed read-only" in blocked[0]
    assert calls == [("search_deals", "Playbill")]
