"""Per-user "Connect Pipedrive": OAuth 2.1 with PKCE against the Pipedrive MCP server's authorization server, the
same flow Claude uses for its connector. No API key and no Developer Hub app: the server's metadata is discovered
(RFC 9728 / RFC 8414) and this app registers itself as a client (RFC 7591). Tokens are stored per user (the
Cloudflare Access email), encrypted with SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import config, store

STATE_TTL_S = 600
REFRESH_MARGIN_S = 60


class OAuthError(RuntimeError):
    pass


def available() -> bool:
    return bool(config.SECRET_KEY and config.BASE_URL)


def redirect_uri() -> str:
    return f"{config.BASE_URL}/oauth/callback"


def make_http_client() -> httpx.AsyncClient:  # replaced in tests
    return httpx.AsyncClient(timeout=20, follow_redirects=True)


def _fernet() -> Fernet:
    if not config.SECRET_KEY:
        raise OAuthError("SECRET_KEY is not set")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.SECRET_KEY.encode()).digest()))


def _encrypt(data: dict) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def _decrypt(blob: bytes) -> dict:
    try:
        return json.loads(_fernet().decrypt(blob))
    except InvalidToken as e:
        raise OAuthError("stored Pipedrive connection can't be decrypted (SECRET_KEY changed?); reconnect") from e


async def _get_json(client: httpx.AsyncClient, urls: list[str]) -> dict | None:
    for url in urls:
        r = await client.get(url, headers={"accept": "application/json"})
        if r.status_code == 200:
            return r.json()
    return None


async def discover(client: httpx.AsyncClient) -> dict:
    mcp = urlsplit(config.PIPEDRIVE_MCP_URL)
    origin = f"{mcp.scheme}://{mcp.netloc}"
    prm = await _get_json(client, [f"{origin}/.well-known/oauth-protected-resource{mcp.path}",
                                   f"{origin}/.well-known/oauth-protected-resource"]) or {}
    issuer = (prm.get("authorization_servers") or [origin])[0].rstrip("/")
    a = urlsplit(issuer)
    a_origin, a_path = f"{a.scheme}://{a.netloc}", a.path.rstrip("/")
    meta = await _get_json(client, [f"{a_origin}/.well-known/oauth-authorization-server{a_path}",
                                    f"{a_origin}/.well-known/openid-configuration{a_path}",
                                    f"{issuer}/.well-known/openid-configuration"])
    if not meta or "authorization_endpoint" not in meta or "token_endpoint" not in meta:
        raise OAuthError(f"no OAuth metadata found for {issuer}")
    return {"issuer": meta.get("issuer", issuer), "authorization_endpoint": meta["authorization_endpoint"],
            "token_endpoint": meta["token_endpoint"], "registration_endpoint": meta.get("registration_endpoint"),
            "resource": prm.get("resource", config.PIPEDRIVE_MCP_URL), "scopes": prm.get("scopes_supported") or []}


async def _client_for(client: httpx.AsyncClient, meta: dict) -> dict:
    if config.PIPEDRIVE_MCP_CLIENT_ID:
        return {"client_id": config.PIPEDRIVE_MCP_CLIENT_ID, "client_secret": config.PIPEDRIVE_MCP_CLIENT_SECRET or None}
    saved = store.get_oauth_client(meta["issuer"], redirect_uri())
    if saved:
        return saved
    if not meta.get("registration_endpoint"):
        raise OAuthError("the server doesn't support dynamic client registration; set PIPEDRIVE_MCP_CLIENT_ID")
    r = await client.post(meta["registration_endpoint"], json={
        "client_name": "Komosion CRM assistant (DeepSeek)", "redirect_uris": [redirect_uri()],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        # a confidential client: this backend keeps the secret (Pipedrive doesn't offer public "none" clients)
        "token_endpoint_auth_method": "client_secret_basic"})
    if r.status_code not in (200, 201):
        raise OAuthError(f"client registration failed: HTTP {r.status_code} {r.text[:200]}")
    d = r.json()
    reg = {"client_id": d["client_id"], "client_secret": d.get("client_secret")}
    store.save_oauth_client(meta["issuer"], redirect_uri(), reg)
    return reg


async def start(user: str) -> str:
    """The URL to send the user's browser to."""
    async with make_http_client() as client:
        meta = await discover(client)
        reg = await _client_for(client, meta)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    store.save_oauth_state(state, user, verifier, time.time())
    params = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect_uri(), "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256", "resource": meta["resource"]}
    scopes = [x for x in config.PIPEDRIVE_MCP_SCOPES if not meta["scopes"] or x in meta["scopes"]]
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


async def finish(user: str, code: str, state: str) -> None:
    saved = store.pop_oauth_state(state)
    if not saved or saved["user"] != user or time.time() - saved["created_at"] > STATE_TTL_S:
        raise OAuthError("this sign-in link is invalid or expired; start again from the app")
    async with make_http_client() as client:
        meta = await discover(client)
        reg = await _client_for(client, meta)
        tok = await _token_request(client, meta["token_endpoint"], reg, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "code_verifier": saved["verifier"], "resource": meta["resource"]})
    _save(user, tok, meta, reg)


async def access_token(user: str) -> str | None:
    """A valid access token for this user, refreshed if needed; None if they haven't connected Pipedrive."""
    if not available():
        return None
    blob = store.get_oauth_token(user)
    if not blob:
        return None
    t = _decrypt(blob)
    if t.get("expires_at") and t["expires_at"] - REFRESH_MARGIN_S < time.time():
        if not t.get("refresh_token"):
            store.delete_oauth_token(user)
            return None
        async with make_http_client() as client:
            reg = {"client_id": t["client_id"], "client_secret": t.get("client_secret")}
            try:
                tok = await _token_request(client, t["token_endpoint"], reg, {
                    "grant_type": "refresh_token", "refresh_token": t["refresh_token"], "resource": t["resource"]})
            except OAuthError:
                store.delete_oauth_token(user)   # refresh refused: they need to connect again
                return None
        tok.setdefault("refresh_token", t["refresh_token"])
        t = _save(user, tok, {"token_endpoint": t["token_endpoint"], "resource": t["resource"]}, reg)
    return t["access_token"]


def connected(user: str) -> bool:
    return available() and store.get_oauth_token(user) is not None


def disconnect(user: str) -> None:
    store.delete_oauth_token(user)


async def _token_request(client: httpx.AsyncClient, url: str, reg: dict, form: dict) -> dict:
    form = {**form, "client_id": reg["client_id"]}
    auth = (reg["client_id"], reg["client_secret"]) if reg.get("client_secret") else None
    r = await client.post(url, data=form, auth=auth, headers={"accept": "application/json"})
    if r.status_code != 200:
        raise OAuthError(f"token request failed: HTTP {r.status_code} {r.text[:200]}")
    tok = r.json()
    if "access_token" not in tok:
        raise OAuthError("token response had no access_token")
    return tok


def _save(user: str, tok: dict, meta: dict, reg: dict) -> dict:
    data = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
            "expires_at": time.time() + int(tok["expires_in"]) if tok.get("expires_in") else None,
            "token_endpoint": meta["token_endpoint"], "resource": meta["resource"],
            "client_id": reg["client_id"], "client_secret": reg.get("client_secret")}
    store.save_oauth_token(user, _encrypt(data))
    return data
