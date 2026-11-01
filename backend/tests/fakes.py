"""Fakes: DeepSeek (streaming chat completions), a Pipedrive MCP server, and its OAuth authorization server."""
import base64
import hashlib
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations


def sse(chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def tool_call_reply(name, arguments, call_id="call_1"):
    half = len(arguments) // 2
    return [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id, "function": {"name": name, "arguments": arguments[:half]}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[half:]}}]}}]},
        {"choices": [], "usage": {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 800, "completion_tokens": 20}},
    ]


def text_reply(text):
    return [
        {"choices": [{"delta": {"reasoning_content": "Let me check. "}}]},
        {"choices": [{"delta": {"content": text[:5]}}]},
        {"choices": [{"delta": {"content": text[5:]}}]},
        {"choices": [], "usage": {"prompt_tokens": 1500, "prompt_cache_hit_tokens": 1000, "completion_tokens": 50}},
    ]


class FakeDeepSeek:
    """Replies with the scripted turns in order and records every request body."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def transport(self):
        def handle(request: httpx.Request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, text=sse(self.replies.pop(0)), headers={"content-type": "text/event-stream"})
        return httpx.MockTransport(handle)


def fake_pipedrive_server(calls: list):
    """Tool names in the shapes a real server might use, reads and writes mixed. `calls` records what reached it."""
    srv = FastMCP("fake-pipedrive")
    ro = ToolAnnotations(readOnlyHint=True)

    @srv.tool(annotations=ro)
    def search_deals(term: str) -> str:
        calls.append(("search_deals", term))
        return json.dumps({"items": [{"id": 4767, "title": "Playbill ROM sprint", "status": "won", "stage_id": 58}]})

    @srv.tool()
    def getPerson(id: int) -> str:
        calls.append(("getPerson", id))
        return json.dumps({"id": id, "name": "Sarah Porter"})

    @srv.tool()
    def list_activities(deal_id: int) -> str:
        calls.append(("list_activities", deal_id))
        return "[]"

    @srv.tool(annotations=ro)
    def deals_summary() -> str:
        calls.append(("deals_summary",))
        return "{}"

    @srv.tool()
    def create_deal(title: str) -> str:
        calls.append(("create_deal", title))
        return "created"

    @srv.tool()
    def updateDeal(id: int, status: str) -> str:
        calls.append(("updateDeal", id))
        return "updated"

    @srv.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def get_and_lock(id: int) -> str:
        calls.append(("get_and_lock", id))
        return "locked"

    @srv.tool()
    def search_and_update_deal(id: int) -> str:
        calls.append(("search_and_update_deal", id))
        return "updated"

    return srv


def fake_session_opener(calls: list, tokens_seen: list | None = None):
    @asynccontextmanager
    async def open_session(token, kind="oauth"):
        if tokens_seen is not None:
            tokens_seen.append(token if kind == "oauth" else f"{kind}:{token}")
        async with create_connected_server_and_client_session(fake_pipedrive_server(calls)) as session:
            yield session
    return open_session


class FakeAuthServer:
    """Protected-resource + authorization-server metadata, dynamic registration and a token endpoint that checks PKCE."""
    MCP = "https://mcp.pipedrive.ai/mcp"
    AS = "https://auth.pipedrive.example"

    def __init__(self):
        self.registrations = 0
        self.challenges = {}       # code -> code_challenge
        self.refresh_ok = True
        self.issued = 0

    def authorize(self, query: dict) -> str:
        """What the user's browser would do at the authorization endpoint: approve and get a code."""
        code = f"code-{len(self.challenges) + 1}"
        self.challenges[code] = query["code_challenge"][0]
        return code

    def transport(self):
        def handle(req: httpx.Request):
            url = str(req.url).split("?")[0]
            if url == "https://mcp.pipedrive.ai/.well-known/oauth-protected-resource/mcp":
                return httpx.Response(200, json={"resource": self.MCP, "authorization_servers": [self.AS], "scopes_supported": ["admin", "base", "deals:full", "contacts:full", "activities:full", "mail-sending:full", "search:read", "users:read"]})
            if url == f"{self.AS}/.well-known/oauth-authorization-server":
                return httpx.Response(200, json={"issuer": self.AS, "authorization_endpoint": f"{self.AS}/authorize",
                                                 "token_endpoint": f"{self.AS}/token", "registration_endpoint": f"{self.AS}/register"})
            if url == f"{self.AS}/register" and req.method == "POST":
                self.registrations += 1
                assert json.loads(req.content)["token_endpoint_auth_method"] == "client_secret_basic"
                return httpx.Response(201, json={"client_id": "cid-123", "client_secret": "csecret"})
            if url == f"{self.AS}/token" and req.method == "POST":
                form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
                assert form["client_id"] == "cid-123" and form["resource"] == self.MCP
                assert req.headers["authorization"] == "Basic " + base64.b64encode(b"cid-123:csecret").decode()
                if form["grant_type"] == "authorization_code":
                    want = self.challenges.pop(form["code"], None)
                    got = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                    if want != got:
                        return httpx.Response(400, json={"error": "invalid_grant"})
                elif form["grant_type"] == "refresh_token" and not self.refresh_ok:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.issued += 1
                return httpx.Response(200, json={"access_token": f"access-{self.issued}", "refresh_token": f"refresh-{self.issued}", "expires_in": 3600})
            return httpx.Response(404)
        return httpx.MockTransport(handle)


class FakePipedriveREST:
    """api.pipedrive.com, read endpoints only; records every request."""
    def __init__(self, good_token="sandbox-token-123"):
        self.requests, self.good = [], good_token

    def transport(self):
        def handle(req: httpx.Request):
            self.requests.append(req)
            if req.headers.get("x-api-token") != self.good:
                return httpx.Response(401, json={"success": False, "error": "unauthorized"})
            if req.url.path == "/v1/users/me":
                return httpx.Response(200, json={"data": {"name": "Yethu Aung", "email": "y@sandbox.test", "company_name": "Komosion Sandbox"}})
            if req.url.path.endswith("/search"):
                return httpx.Response(200, json={"data": {"items": [{"item": {"id": 7, "title": "Sandbox deal"}}]}})
            return httpx.Response(200, json={"data": {"id": 7}})
        return httpx.MockTransport(handle)
