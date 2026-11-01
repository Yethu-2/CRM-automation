"""HTTP API + the chat page. Runs behind Cloudflare Access; the container itself listens on localhost only."""
from __future__ import annotations

import html
import json
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import agent, config, google_oauth, oauth, pipedrive_mcp, skills, store
from .google_tools import GoogleWorkspace
from .pipedrive_mcp import PipedriveMCP
from .pipedrive_rest import PipedriveREST
from .tools import Toolbox

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Komosion CRM — DeepSeek")


def make_llm_client() -> httpx.AsyncClient:      # replaced in tests
    return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15))


open_pipedrive_session = pipedrive_mcp.open_session   # replaced in tests


def make_pipedrive_rest(token: str) -> PipedriveREST:  # replaced in tests
    return PipedriveREST(token)


def make_google(token: str) -> GoogleWorkspace:       # replaced in tests
    return GoogleWorkspace(token)


def current_user(request: Request) -> str:
    """The Cloudflare Access email. Without Access in front (local dev) everyone is "local"; production sets
    REQUIRE_ACCESS_EMAIL=true so a request that didn't come through Access is refused."""
    email = (request.headers.get("cf-access-authenticated-user-email") or "").strip().lower()
    if email:
        return email
    if config.REQUIRE_ACCESS_EMAIL:
        raise HTTPException(401, "sign in through Cloudflare Access")
    return "local"


class NewConversation(BaseModel):
    model: str | None = None


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    model: str | None = None


@app.get("/")
def index(user: str = Depends(current_user)) -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def get_config(user: str = Depends(current_user)) -> dict:
    s = skills.discover()
    return {"models": config.MODELS, "default_model": config.DEFAULT_MODEL, "deepseek_configured": bool(config.DEEPSEEK_API_KEY),
            "pipedrive": oauth.status(user),
            "google": google_oauth.status(user),
            "skills": [{"name": x.name, "description": x.description, "always_loaded": x.name in config.ALWAYS_LOADED_SKILLS}
                       for x in s.values()],
            "user": user}


# ---- Connect Pipedrive (per user, OAuth via the Pipedrive MCP server) ----
@app.get("/oauth/pipedrive/start")
async def pipedrive_start(user: str = Depends(current_user)):
    if not oauth.available():
        raise HTTPException(503, "Pipedrive connection isn't set up on this server (BASE_URL and SECRET_KEY)")
    try:
        return RedirectResponse(await oauth.start(user), status_code=302)
    except (oauth.OAuthError, httpx.HTTPError) as e:
        return _page("Couldn't start the Pipedrive sign-in", str(e))


@app.get("/oauth/callback")
async def pipedrive_callback(request: Request, user: str = Depends(current_user)):
    q = request.query_params
    if q.get("error"):
        return _page("Pipedrive wasn't connected", q.get("error_description") or q["error"])
    try:
        await oauth.finish(user, q.get("code", ""), q.get("state", ""))
    except (oauth.OAuthError, httpx.HTTPError) as e:
        return _page("Pipedrive wasn't connected", str(e))
    return RedirectResponse("/?pipedrive=connected", status_code=302)


class PipedriveToken(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@app.post("/api/pipedrive/token")
async def pipedrive_token(body: PipedriveToken, user: str = Depends(current_user)) -> dict:
    """Connect with an API token (e.g. a developer sandbox). Checks it, then prefers the official MCP server (with its
    read-only tool filter) and falls back to the read-only REST client if the MCP server won't take the token."""
    if not config.SECRET_KEY:
        raise HTTPException(503, "SECRET_KEY isn't set on this server")
    token = body.token.strip()
    rest = make_pipedrive_rest(token)
    try:
        account = await rest.me()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Pipedrive didn't accept that token ({type(e).__name__}: {str(e)[:120]})") from e
    finally:
        await rest.aclose()
    transport = "rest"
    try:
        async with open_pipedrive_session(token, kind="api_token") as session:
            if (await PipedriveMCP.create(session)).read_tools:
                transport = "mcp"
    except Exception:  # noqa: BLE001 - the MCP server may not take API tokens; REST works either way
        pass
    oauth.save_api_token(user, token, transport, account)
    return {"connected": True, "transport": transport, "account": account}


@app.post("/api/pipedrive/disconnect")
def pipedrive_disconnect(user: str = Depends(current_user)) -> dict:
    oauth.disconnect(user)
    return {"ok": True}


# ---- Connect Google (per user, read-only scopes; off unless GOOGLE_ENABLED) ----
@app.get("/oauth/google/start")
def google_start(user: str = Depends(current_user)):
    try:
        return RedirectResponse(google_oauth.start(user), status_code=302)
    except oauth.OAuthError as e:
        return _page("Couldn't start the Google sign-in", str(e))


@app.get("/oauth/google/callback")
async def google_callback(request: Request, user: str = Depends(current_user)):
    q = request.query_params
    if q.get("error"):
        return _page("Google wasn't connected", q.get("error_description") or q["error"])
    try:
        await google_oauth.finish(user, q.get("code", ""), q.get("state", ""))
    except (oauth.OAuthError, httpx.HTTPError) as e:
        return _page("Google wasn't connected", str(e))
    return RedirectResponse("/?google=connected", status_code=302)


@app.post("/api/google/disconnect")
async def google_disconnect(user: str = Depends(current_user)) -> dict:
    await google_oauth.disconnect(user)
    return {"ok": True}


# ---- conversations ----
@app.get("/api/conversations")
def conversations(user: str = Depends(current_user)) -> list[dict]:
    return store.list_conversations(user)


@app.post("/api/conversations")
def create_conversation(body: NewConversation, user: str = Depends(current_user)) -> dict:
    return store.new_conversation(_model(body.model), user)


@app.get("/api/conversations/{conv_id}")
def conversation(conv_id: str, user: str = Depends(current_user)) -> dict:
    conv = store.get_conversation(conv_id, user)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return conv


@app.delete("/api/conversations/{conv_id}")
def remove_conversation(conv_id: str, user: str = Depends(current_user)) -> dict:
    store.delete_conversation(conv_id, user)
    return {"ok": True}


@app.post("/api/conversations/{conv_id}/messages")
async def send(conv_id: str, body: NewMessage, user: str = Depends(current_user)) -> StreamingResponse:
    conv = store.get_conversation(conv_id, user)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(503, "DEEPSEEK_API_KEY is not set")
    model = _model(body.model or conv["model"])
    user_msg = {"role": "user", "content": body.text}
    store.append_messages(conv_id, [user_msg], title=body.text.strip().splitlines()[0], model=model)

    async def events():
        new: list[dict] = []
        done, error = None, None
        try:
            async with AsyncExitStack() as stack:
                pipedrive = None
                cred = await oauth.credential(user)
                if cred:
                    try:
                        if cred["transport"] == "rest":
                            pipedrive = make_pipedrive_rest(cred["token"])
                            stack.push_async_callback(pipedrive.aclose)
                        else:
                            session = await stack.enter_async_context(open_pipedrive_session(cred["token"], kind=cred["kind"]))
                            pipedrive = await PipedriveMCP.create(session)
                        yield _sse({"type": "pipedrive", "tools": sorted(pipedrive.read_tools), "blocked": pipedrive.blocked})
                    except Exception as e:  # noqa: BLE001 - answer without CRM data rather than not at all
                        yield _sse({"type": "warning", "message": f"Pipedrive unavailable ({type(e).__name__}: {e}); answering without CRM data."})
                google = None
                gtoken = await google_oauth.access_token(user)
                if gtoken:
                    google = make_google(gtoken)
                    stack.push_async_callback(google.aclose)
                client = await stack.enter_async_context(make_llm_client())
                async for ev in agent.run_turn(client, Toolbox(skills.discover(), pipedrive, google), model, [*conv["messages"], user_msg], new):
                    if ev["type"] == "done":
                        done = ev
                    elif ev["type"] == "error":
                        error = ev["message"]
                    yield _sse(ev)
        except Exception as e:  # noqa: BLE001 - report to the browser, keep what was produced
            error = f"{type(e).__name__}: {e}"
            yield _sse({"type": "error", "message": error})
        finally:
            # Only keep complete exchanges, so the next request never sends DeepSeek a dangling tool call.
            store.append_messages(conv_id, _complete(new))
            store.add_run(conv_id, body.text, done, error, user)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs.csv")
def runs_csv(user: str = Depends(current_user)) -> PlainTextResponse:
    return PlainTextResponse(store.runs_csv(user), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=deepseek-runs.csv"})


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


def _page(title: str, detail: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
                        f"<body style='font:16px system-ui;max-width:560px;margin:15vh auto;padding:0 16px'>"
                        f"<h2>{html.escape(title)}</h2><p>{html.escape(detail)}</p><p><a href='/'>Back to the app</a></p>", status_code=400)


def _model(name: str | None) -> str:
    if name and name not in config.MODELS:
        raise HTTPException(422, f"model must be one of {config.MODELS}")
    return name or config.DEFAULT_MODEL


def _complete(msgs: list[dict]) -> list[dict]:
    """Drop the last tool-calling assistant message (and anything after it) if not all its tool results arrived."""
    out = list(msgs)
    while True:
        idx = max((i for i, m in enumerate(out) if m["role"] == "assistant" and m.get("tool_calls")), default=None)
        if idx is None:
            return out
        wanted = {c["id"] for c in out[idx]["tool_calls"]}
        if wanted <= {m["tool_call_id"] for m in out[idx + 1:] if m["role"] == "tool"}:
            return out
        out = out[:idx]
