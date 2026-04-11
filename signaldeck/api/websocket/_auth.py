"""Shared WebSocket authorization helper.

Runs the same auth gate as AuthMiddleware against a WebSocket handshake.
Handlers call this before calling `await websocket.accept()`, and close
with 1008 (policy violation) if the result is False.
"""
from fastapi import WebSocket

from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client
from signaldeck.api.server import _state


async def ws_authorized(websocket: WebSocket) -> bool:
    """Return True if the WebSocket handshake is allowed through.

    Accepts loopback/LAN origins without credentials. For remote origins,
    accepts a Bearer authorization header, otherwise a valid sd_remember
    cookie. Returns False if auth is enabled and none of these pass.
    """
    auth_mgr = _state.get("auth")
    if auth_mgr is None:
        return True  # Auth disabled entirely.

    config = _state.get("config", {}) or {}
    auth_cfg = config.get("auth", {}) if isinstance(config, dict) else {}
    allowlist = auth_cfg.get("lan_allowlist") or DEFAULT_LAN_ALLOWLIST

    client_ip = ""
    if auth_cfg.get("trust_x_forwarded_for", False):
        xff = websocket.headers.get("x-forwarded-for", "")
        if xff:
            client_ip = xff.split(",")[0].strip()
    if not client_ip and websocket.client is not None:
        client_ip = websocket.client.host

    if is_lan_client(client_ip, allowlist):
        return True

    # Bearer header (rare on WS, but possible from native clients)
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_mgr.verify_token(auth_header[7:]):
        return True

    # Remember-me cookie — the normal browser path
    cookie = websocket.cookies.get("sd_remember")
    if cookie:
        db = _state.get("db")
        if db is not None and await auth_mgr.verify_remember_token(db, cookie):
            return True

    return False
