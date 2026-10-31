"""HTTP API + the chat page. Runs behind Cloudflare Access; the container itself listens on localhost only."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import agent, config, skills, store
from .pipedrive import Pipedrive
from .tools import Toolbox

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Komosion CRM — DeepSeek")


def make_llm_client() -> httpx.AsyncClient:      # replaced in tests
    return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15))


def make_pipedrive() -> Pipedrive:               # replaced in tests
    return Pipedrive()


class NewConversation(BaseModel):
    model: str | None = None


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    model: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def get_config(request: Request) -> dict:
    s = skills.discover()
    return {"models": config.MODELS, "default_model": config.DEFAULT_MODEL,
            "deepseek_configured": bool(config.DEEPSEEK_API_KEY), "pipedrive_configured": bool(config.PIPEDRIVE_API_TOKEN),
            "skills": [{"name": x.name, "description": x.description, "always_loaded": x.name in config.ALWAYS_LOADED_SKILLS}
                       for x in s.values()],
            "user": request.headers.get("cf-access-authenticated-user-email")}


@app.get("/api/conversations")
def conversations() -> list[dict]:
    return store.list_conversations()


@app.post("/api/conversations")
def create_conversation(body: NewConversation) -> dict:
    return store.new_conversation(_model(body.model))


@app.get("/api/conversations/{conv_id}")
def conversation(conv_id: str) -> dict:
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


@app.delete("/api/conversations/{conv_id}")
def remove_conversation(conv_id: str) -> dict:
    store.delete_conversation(conv_id)
    return {"ok": True}


@app.post("/api/conversations/{conv_id}/messages")
async def send(conv_id: str, body: NewMessage, request: Request) -> StreamingResponse:
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(503, "DEEPSEEK_API_KEY is not set")
    model = _model(body.model or conv["model"])
    user_msg = {"role": "user", "content": body.text}
    store.append_messages(conv_id, [user_msg], title=body.text.strip().splitlines()[0], model=model)
    user_email = request.headers.get("cf-access-authenticated-user-email")

    async def events():
        new: list[dict] = []
        done, error = None, None
        pd = make_pipedrive()
        try:
            async with make_llm_client() as client:
                toolbox = Toolbox(skills.discover(), pd)
                async for ev in agent.run_turn(client, toolbox, model, [*conv["messages"], user_msg], new):
                    if ev["type"] == "done":
                        done = ev
                    elif ev["type"] == "error":
                        error = ev["message"]
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 - report to the browser, keep what was produced
            error = f"{type(e).__name__}: {e}"
            yield f"data: {json.dumps({'type': 'error', 'message': error})}\n\n"
        finally:
            await pd.aclose()
            # Only keep complete exchanges, so the next request never sends DeepSeek a dangling tool call.
            store.append_messages(conv_id, _complete(new))
            store.add_run(conv_id, body.text, done, error, user_email)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs.csv")
def runs_csv() -> PlainTextResponse:
    return PlainTextResponse(store.runs_csv(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=deepseek-runs.csv"})


def _model(name: str | None) -> str:
    if name and name not in config.MODELS:
        raise HTTPException(422, f"model must be one of {config.MODELS}")
    return name or config.DEFAULT_MODEL


def _complete(msgs: list[dict]) -> list[dict]:
    """Drop a trailing assistant tool-call message whose tool results never arrived (an aborted turn)."""
    out = list(msgs)
    while True:
        idx = max((i for i, m in enumerate(out) if m["role"] == "assistant" and m.get("tool_calls")), default=None)
        if idx is None:
            return out
        wanted = {c["id"] for c in out[idx]["tool_calls"]}
        if wanted <= {m["tool_call_id"] for m in out[idx + 1:] if m["role"] == "tool"}:
            return out
        out = out[:idx]
