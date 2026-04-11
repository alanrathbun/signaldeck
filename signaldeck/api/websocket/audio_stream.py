import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from signaldeck.api.websocket._auth import ws_authorized

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-client state: {"freq": float | None, "is_lan": bool, "remote_addr": str}
_audio_clients: dict = {}

# Shared state for audio streaming from scanner
_audio_request: dict = {"frequency_hz": None, "active": False, "modulation": None, "volume": None}


def get_audio_request() -> dict:
    """Called by the scanner to check if audio streaming is requested."""
    return _audio_request


def resolve_effective_audio_mode(configured_mode: str) -> str:
    """Decide the effective audio mode from the configured mode + live subscribers.

    - configured_mode == "gqrx" → always "gqrx"
    - configured_mode == "pcm_stream" → always "pcm_stream"
    - configured_mode == "auto":
        - Any subscriber with freq not None AND is_lan False → "pcm_stream"
        - Otherwise → "gqrx"
    """
    if configured_mode == "gqrx":
        return "gqrx"
    if configured_mode == "pcm_stream":
        return "pcm_stream"
    # auto
    for info in _audio_clients.values():
        if isinstance(info, dict) and info.get("freq") is not None and not info.get("is_lan", True):
            return "pcm_stream"
    return "gqrx"


async def send_audio_chunk(frequency_hz: float, audio_bytes: bytes) -> None:
    """Send demodulated audio to subscribed WebSocket clients."""
    global _audio_clients
    for ws, info in list(_audio_clients.items()):
        if not isinstance(info, dict):
            continue
        sub_freq = info.get("freq")
        if sub_freq is not None and abs(sub_freq - frequency_hz) < 5000:
            try:
                await ws.send_bytes(audio_bytes)
            except Exception:
                _audio_clients.pop(ws, None)


@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    global _audio_clients
    if not await ws_authorized(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    client_addr = websocket.client.host if websocket.client else ""
    _audio_clients[websocket] = {"freq": None, "is_lan": True, "remote_addr": client_addr}
    logger.debug("Audio WebSocket client connected")

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "subscribe":
                freq = data.get("frequency_hz", 0)
                modulation = data.get("modulation")
                volume = data.get("volume")
                # Classify this client's origin against the LAN allowlist so
                # the audio-mode resolver can decide.
                from signaldeck.api.auth import DEFAULT_LAN_ALLOWLIST, is_lan_client
                from signaldeck.api.server import _state
                cfg = _state.get("config", {}) or {}
                allowlist = cfg.get("auth", {}).get("lan_allowlist") or DEFAULT_LAN_ALLOWLIST
                client_addr = websocket.client.host if websocket.client else ""
                _audio_clients[websocket] = {
                    "freq": freq,
                    "is_lan": is_lan_client(client_addr, allowlist),
                    "remote_addr": client_addr,
                }
                _audio_request["frequency_hz"] = freq
                _audio_request["active"] = True
                _audio_request["modulation"] = modulation
                if volume is not None:
                    _audio_request["volume"] = volume
                logger.debug("Audio subscribe: %.3f MHz (mod=%s)", freq / 1e6, modulation)
                # Include effective mode so the frontend can detect silence in gqrx-pinned mode
                scanner_cfg = cfg.get("scanner", {})
                effective = resolve_effective_audio_mode(
                    scanner_cfg.get("audio_mode", "auto")
                )
                await websocket.send_json({
                    "type": "subscribed",
                    "frequency_hz": freq,
                    "effective_mode": effective,
                })
            elif data.get("type") == "unsubscribe":
                existing = _audio_clients.get(websocket, {})
                _audio_clients[websocket] = {
                    "freq": None,
                    "is_lan": existing.get("is_lan", True) if isinstance(existing, dict) else True,
                    "remote_addr": existing.get("remote_addr", "") if isinstance(existing, dict) else "",
                }
                # Check if any client still subscribed
                any_tuned = any(
                    isinstance(info, dict) and info.get("freq") is not None
                    for info in _audio_clients.values()
                )
                if not any_tuned:
                    _audio_request["frequency_hz"] = None
                    _audio_request["active"] = False
                    _audio_request["modulation"] = None
                await websocket.send_json({"type": "unsubscribed"})
            elif data.get("type") == "volume":
                _audio_request["volume"] = data.get("level")
                logger.debug("Audio volume: %s", data.get("level"))
    except WebSocketDisconnect:
        pass
    finally:
        _audio_clients.pop(websocket, None)
        any_tuned = any(
            isinstance(info, dict) and info.get("freq") is not None
            for info in _audio_clients.values()
        )
        if not any_tuned:
            _audio_request["frequency_hz"] = None
            _audio_request["active"] = False
            _audio_request["modulation"] = None
        logger.debug("Audio WebSocket client disconnected")
