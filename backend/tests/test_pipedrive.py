import asyncio

import pytest

from app.pipedrive import Pipedrive, ReadOnlyViolation
from fakes import FakePipedrive


def run(coro):
    return asyncio.run(coro)


def test_the_client_has_no_way_to_write():
    for name in ("post", "put", "patch", "delete", "request", "send"):
        assert not hasattr(Pipedrive, name), name


def test_every_read_is_a_get_with_the_token_header():
    fake = FakePipedrive()
    pd = Pipedrive(token="secret", transport=fake.transport())

    async def go():
        await pd.search("organizations", "RMIT")
        await pd.get_one("deals", 4767)
        await pd.activities(deal_id=4767)
        await pd.notes(org_id=2246)
        await pd.aclose()
    run(go())
    assert [r.method for r in fake.requests] == ["GET"] * 4
    assert all(r.headers["x-api-token"] == "secret" for r in fake.requests)
    assert [r.url.path for r in fake.requests] == ["/api/v2/organizations/search", "/api/v2/deals/4767", "/api/v2/activities", "/v1/notes"]
    assert "api_token" not in str(fake.requests[0].url)   # never in the URL, where it could end up in logs


def test_paths_off_the_allowlist_are_refused_before_any_request():
    fake = FakePipedrive()
    pd = Pipedrive(token="secret", transport=fake.transport())
    for path in ("/v1/deals/1/followers", "/api/v2/deals/1/products", "/v1/users", "/api/v2/deals/../users"):
        with pytest.raises(ReadOnlyViolation):
            run(pd.get(path))
    with pytest.raises(ValueError):
        run(pd.search("users", "x"))
    assert fake.requests == []


def test_missing_token_is_an_error_not_an_anonymous_call():
    fake = FakePipedrive()
    with pytest.raises(RuntimeError):
        run(Pipedrive(token="", transport=fake.transport()).search("deals", "x"))
    assert fake.requests == []
