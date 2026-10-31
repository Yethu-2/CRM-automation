"""Pipedrive through its official MCP server (the same one Claude's Pipedrive connector uses), read-only.

The server exposes write tools too. Only tools that are clearly reads are offered to DeepSeek, and a call to anything
else is refused here, before it reaches Pipedrive. (The Phase 2 test log flagged that the live connection exposes
write tools and that read-only must be enforced in code, not by prompt.)"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client

from . import config

PREFIX = "pipedrive__"
_READ = re.compile(r"(^|_)(get|list|search|find|retrieve|fetch|read|lookup|query|describe|count)(_|$)")
_WRITE = re.compile(r"(^|_)(create|add|update|edit|delete|remove|merge|post|put|patch|set|archive|unarchive|convert|"
                    r"link|unlink|send|upload|mark|assign|move|duplicate|restore|attach|detach|write|import|bulk)(_|$)")


def _words(name: str) -> str:
    """searchDeals / search-deals / deals.search → search_deals / deals_search, so verbs can be matched as words."""
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()).strip("_")


def is_read_only(tool: types.Tool) -> bool:
    """A tool is offered only if nothing says it writes and something says it reads: a read verb in its name, or the
    server's own readOnlyHint. Any write verb, readOnlyHint=False or destructiveHint=True rules it out."""
    a = tool.annotations
    if a is not None and (a.readOnlyHint is False or a.destructiveHint is True):
        return False
    words = _words(tool.name)
    if _WRITE.search(words):
        return False
    return bool(_READ.search(words)) or (a is not None and a.readOnlyHint is True)


class PipedriveMCP:
    """Wraps an initialised MCP ClientSession. Use `await PipedriveMCP.create(session)`."""

    def __init__(self, session: ClientSession, tools: list[types.Tool]):
        self.session = session
        self.all_tools = tools
        self.read_tools = {self.local_name(t.name): t for t in tools if is_read_only(t)}

    @classmethod
    async def create(cls, session: ClientSession) -> PipedriveMCP:
        tools, cursor = [], None
        while True:
            page = await session.list_tools(cursor) if cursor else await session.list_tools()
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                return cls(session, tools)

    @staticmethod
    def local_name(name: str) -> str:
        return (PREFIX + re.sub(r"[^A-Za-z0-9_-]", "_", name))[:64]

    @property
    def blocked(self) -> list[str]:
        return sorted(t.name for t in self.all_tools if not is_read_only(t))

    def schemas(self) -> list[dict]:
        out = []
        for local, t in self.read_tools.items():
            params = t.inputSchema if isinstance(t.inputSchema, dict) and t.inputSchema else {"type": "object", "properties": {}}
            out.append({"type": "function", "function": {
                "name": local, "description": f"[Pipedrive, read-only] {t.description or t.name}"[:1024], "parameters": params}})
        return out

    def handles(self, local: str) -> bool:
        return local.startswith(PREFIX)

    async def call(self, local: str, args: dict[str, Any]) -> tuple[str, bool]:
        tool = self.read_tools.get(local)
        if tool is None:  # a write tool, or one the server doesn't have: never forwarded
            return json.dumps({"error": f"{local} is not an allowed read-only Pipedrive tool"}), False
        result = await self.session.call_tool(tool.name, args)
        parts = [c.text for c in result.content if isinstance(c, types.TextContent)]
        if not parts and result.structuredContent is not None:
            parts = [json.dumps(result.structuredContent, ensure_ascii=False)]
        return "\n".join(parts) or "(empty result)", not result.isError


@asynccontextmanager
async def open_session(access_token: str) -> AsyncIterator[ClientSession]:
    async with streamablehttp_client(config.PIPEDRIVE_MCP_URL, headers={"Authorization": f"Bearer {access_token}"},
                                     timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
