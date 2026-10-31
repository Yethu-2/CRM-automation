"""Fake DeepSeek (streaming chat completions) and fake Pipedrive, as httpx transports."""
import json

import httpx


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


class FakePipedrive:
    def __init__(self):
        self.requests = []

    def transport(self):
        def handle(request: httpx.Request):
            self.requests.append(request)
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"success": True, "data": {"items": [{"item": {"id": 2246, "name": "RMIT University Vietnam"}}]}})
            return httpx.Response(200, json={"success": True, "data": {"id": 2246, "name": "RMIT University Vietnam"}})
        return httpx.MockTransport(handle)
