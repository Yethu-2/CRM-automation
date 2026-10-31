"""Per-user "Connect Google": Gmail, Drive and Calendar, read-only. Google enforces read-only through the scopes
(gmail.readonly, drive.readonly, calendar.readonly): with these tokens nothing can be sent, edited or deleted.
Off unless GOOGLE_ENABLED=true, because the content DeepSeek reads is sent to DeepSeek's (China-hosted) API."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx

from . import config, oauth, store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# Google reports "email" back under its full name; it identifies the account and grants no data access.
IDENTITY_SCOPES = {"openid", "email", "https://www.googleapis.com/auth/userinfo.email"}
SCOPES = ["openid", "email",
          "https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/calendar.readonly"]


def available() -> bool:
    return config.GOOGLE_ENABLED and bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET) and oauth.available()


def redirect_uri() -> str:
    return f"{config.BASE_URL}/oauth/google/callback"


def make_http_client() -> httpx.AsyncClient:  # replaced in tests
    return httpx.AsyncClient(timeout=20)


def start(user: str) -> str:
    if not available():
        raise oauth.OAuthError("Google connection is switched off on this server")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    store.save_google_state(state, user, verifier, time.time())
    params = {"client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri(), "response_type": "code",
              "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
              "access_type": "offline", "prompt": "consent"}
    if "@" in user:
        params["login_hint"] = user
    return AUTH_URL + "?" + urlencode(params)


async def finish(user: str, code: str, state: str) -> None:
    saved = store.pop_google_state(state)
    if not saved or saved["user"] != user or time.time() - saved["created_at"] > oauth.STATE_TTL_S:
        raise oauth.OAuthError("this sign-in link is invalid or expired; start again from the app")
    async with make_http_client() as client:
        tok = await _token(client, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                                    "code_verifier": saved["verifier"]})
    granted = set(tok.get("scope", "").split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES[2:] if s not in granted]
    if missing:   # Google lets people untick scopes on the consent screen
        raise oauth.OAuthError(f"read access wasn't granted for: {', '.join(missing)}. Connect again and leave those boxes ticked.")
    if granted - set(SCOPES) - IDENTITY_SCOPES:
        # never hold a token that could write, whatever Google returns
        raise oauth.OAuthError("Google returned more access than read-only; remove this app at myaccount.google.com/permissions and connect again")
    _save(user, tok, account=_email_from_id_token(tok.get("id_token")))


async def access_token(user: str) -> str | None:
    if not available():
        return None
    blob = store.get_google_token(user)
    if not blob:
        return None
    t = oauth._decrypt(blob)
    if t["expires_at"] - oauth.REFRESH_MARGIN_S < time.time():
        try:
            async with make_http_client() as client:
                tok = await _token(client, {"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
        except oauth.OAuthError:
            store.delete_google_token(user)   # e.g. testing-mode tokens lapse after 7 days: reconnect
            return None
        tok["refresh_token"] = t["refresh_token"]   # Google doesn't resend it
        t = _save(user, tok, account=t.get("account"))
    return t["access_token"]


def status(user: str) -> dict:
    blob = store.get_google_token(user) if available() else None
    return {"available": available(), "connected": blob is not None,
            "account": oauth._decrypt(blob).get("account") if blob else None}


async def disconnect(user: str) -> None:
    blob = store.get_google_token(user)
    store.delete_google_token(user)
    if blob:  # also revoke at Google, so the grant disappears from their account too
        try:
            async with make_http_client() as client:
                await client.post(REVOKE_URL, data={"token": oauth._decrypt(blob)["refresh_token"]})
        except (httpx.HTTPError, oauth.OAuthError):
            pass


async def _token(client: httpx.AsyncClient, form: dict) -> dict:
    r = await client.post(TOKEN_URL, data={**form, "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET})
    if r.status_code != 200:
        raise oauth.OAuthError(f"Google token request failed: HTTP {r.status_code} {r.text[:200]}")
    tok = r.json()
    if "access_token" not in tok or (form["grant_type"] == "authorization_code" and not tok.get("refresh_token")):
        raise oauth.OAuthError("Google didn't return the expected tokens; connect again")
    return tok


def _email_from_id_token(id_token: str | None) -> str | None:
    """The account they picked (may differ from their Cloudflare login). Shown only; the token came straight from
    Google's token endpoint over TLS, so the payload isn't re-verified."""
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email")
    except (AttributeError, IndexError, ValueError):
        return None


def _save(user: str, tok: dict, account: str | None) -> dict:
    data = {"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
            "expires_at": time.time() + int(tok.get("expires_in", 3600)), "account": account}
    store.save_google_token(user, oauth._encrypt(data))
    return data
