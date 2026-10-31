"""Read-only Pipedrive client. This is the only code that talks to Pipedrive, and it can only send GET requests to
an allowlist of read endpoints: there is no method for anything else, so no prompt can make it write. (The Phase 2
test log flagged that the live connection exposes write tools; read-only here is enforced in code, not by prompt.)"""
from __future__ import annotations

import re
from typing import Any

import httpx

from . import config

ENTITIES = ("deals", "persons", "organizations")
_ALLOWED = re.compile(r"^/api/v2/(deals|persons|organizations)(/search|/\d+)?$|^/api/v2/activities$|^/v1/notes$")


class ReadOnlyViolation(PermissionError):
    pass


class Pipedrive:
    def __init__(self, token: str | None = None, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._token = token if token is not None else config.PIPEDRIVE_API_TOKEN
        self._client = httpx.AsyncClient(base_url=base_url or config.PIPEDRIVE_BASE_URL, transport=transport, timeout=30,
                                         headers={"x-api-token": self._token, "accept": "application/json"})

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not _ALLOWED.match(path):
            raise ReadOnlyViolation(f"path not on the read allowlist: {path}")
        if not self._token:
            raise RuntimeError("PIPEDRIVE_API_TOKEN is not set")
        r = await self._client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        if r.status_code >= 400:
            raise RuntimeError(f"Pipedrive HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    # ---- the reads the tools use ----
    async def search(self, entity: str, term: str, limit: int = 10) -> Any:
        _entity(entity)
        return await self.get(f"/api/v2/{entity}/search", {"term": term, "limit": min(max(limit, 1), 50)})

    async def get_one(self, entity: str, item_id: int) -> Any:
        _entity(entity)
        return await self.get(f"/api/v2/{entity}/{int(item_id)}")

    async def activities(self, deal_id: int | None = None, person_id: int | None = None, org_id: int | None = None, limit: int = 50) -> Any:
        return await self.get("/api/v2/activities", {"deal_id": deal_id, "person_id": person_id, "org_id": org_id, "limit": min(limit, 100)})

    async def notes(self, deal_id: int | None = None, person_id: int | None = None, org_id: int | None = None, limit: int = 50) -> Any:
        return await self.get("/v1/notes", {"deal_id": deal_id, "person_id": person_id, "org_id": org_id, "limit": min(limit, 100)})

    async def aclose(self) -> None:
        await self._client.aclose()


def _entity(entity: str) -> None:
    if entity not in ENTITIES:
        raise ValueError(f"entity must be one of {ENTITIES}")
