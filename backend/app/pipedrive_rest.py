"""Read-only Pipedrive REST client, for API-token connections the MCP server won't take (e.g. a developer sandbox).

It can only send GET requests to an allowlist of read endpoints: there is no method for anything else, so no prompt
can make it write. Same tool shape as PipedriveMCP (schemas / handles / call), so the rest of the app doesn't care
which one a user is connected through."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from . import config

ENTITIES = ("deals", "persons", "organizations")
_ALLOWED = re.compile(r"^/api/v2/(deals|persons|organizations)(/search|/\d+)?$|^/api/v2/activities$|^/v1/notes$|^/v1/users/me$")
_ENTITY = {"type": "string", "enum": list(ENTITIES)}
_ID = {"type": "integer"}
SCHEMAS = [
    {"type": "function", "function": {
        "name": "pipedrive_search",
        "description": "[Pipedrive, read-only] Search deals, persons or organizations by name, email or other text.",
        "parameters": {"type": "object", "properties": {
            "entity": _ENTITY, "term": {"type": "string", "description": "At least 2 characters"},
            "limit": {"type": "integer", "description": "1-50, default 10"}}, "required": ["entity", "term"]}}},
    {"type": "function", "function": {
        "name": "pipedrive_get",
        "description": "[Pipedrive, read-only] Get one deal, person or organization by ID, with all its fields.",
        "parameters": {"type": "object", "properties": {"entity": _ENTITY, "id": _ID}, "required": ["entity", "id"]}}},
    {"type": "function", "function": {
        "name": "pipedrive_activities",
        "description": "[Pipedrive, read-only] List activities (calls, meetings, tasks) for a deal, person or organization.",
        "parameters": {"type": "object", "properties": {"deal_id": _ID, "person_id": _ID, "org_id": _ID}}}},
    {"type": "function", "function": {
        "name": "pipedrive_notes",
        "description": "[Pipedrive, read-only] List notes attached to a deal, person or organization.",
        "parameters": {"type": "object", "properties": {"deal_id": _ID, "person_id": _ID, "org_id": _ID}}}},
]
NAMES = {s["function"]["name"] for s in SCHEMAS}


class ReadOnlyViolation(PermissionError):
    pass


class PipedriveREST:
    def __init__(self, token: str, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 bearer: bool = False):
        """bearer=True for an OAuth app token (sent to the company's api_domain); otherwise an API token."""
        self._token = token
        auth = {"Authorization": f"Bearer {token}"} if bearer else {"x-api-token": token}
        self._client = httpx.AsyncClient(base_url=(base_url or config.PIPEDRIVE_API_URL).rstrip("/"), transport=transport, timeout=30,
                                         headers={**auth, "accept": "application/json"})
        self.read_tools = sorted(NAMES)
        self.blocked: list[str] = []   # nothing to block: this client has no write calls at all

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not _ALLOWED.match(path):
            raise ReadOnlyViolation(f"path not on the read allowlist: {path}")
        if not self._token:
            raise RuntimeError("no Pipedrive API token")
        r = await self._client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        if r.status_code >= 400:
            raise RuntimeError(f"Pipedrive HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def me(self) -> dict[str, Any]:
        """Who the token belongs to (used to check it when connecting)."""
        d = (await self.get("/v1/users/me")).get("data") or {}
        return {"name": d.get("name"), "email": d.get("email"), "company": d.get("company_name") or d.get("company_domain")}

    # ---- the tool interface (same as PipedriveMCP) ----
    def schemas(self) -> list[dict]:
        return SCHEMAS

    def handles(self, name: str) -> bool:
        return name in NAMES

    async def call(self, name: str, a: dict[str, Any]) -> tuple[str, bool]:
        if name == "pipedrive_search":
            if len(str(a.get("term", "")).strip()) < 2:
                raise ValueError("term must be at least 2 characters")
            _entity(a["entity"])
            out = await self.get(f"/api/v2/{a['entity']}/search", {"term": a["term"], "limit": min(max(int(a.get("limit", 10)), 1), 50)})
        elif name == "pipedrive_get":
            _entity(a["entity"])
            out = await self.get(f"/api/v2/{a['entity']}/{int(a['id'])}")
        elif name in ("pipedrive_activities", "pipedrive_notes"):
            ids = {k: a.get(k) for k in ("deal_id", "person_id", "org_id")}
            if not any(ids.values()):
                raise ValueError("give one of deal_id, person_id or org_id")
            out = await self.get("/api/v2/activities" if name == "pipedrive_activities" else "/v1/notes", {**ids, "limit": 50})
        else:
            raise ValueError(f"unknown tool {name!r}")
        return json.dumps(out, ensure_ascii=False, separators=(",", ":")), True

    async def aclose(self) -> None:
        await self._client.aclose()


def _entity(entity: str) -> None:
    if entity not in ENTITIES:
        raise ValueError(f"entity must be one of {ENTITIES}")
