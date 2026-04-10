import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_audio_clients: dict[WebSocket, float | None] = {}

# Shared state for audio streaming from scanner
_audio_request: dict = {"frequency_hz": None, "active": False, "modulation": None, "volume": None}


def get_audio_request() -> dict:
    """Called by the scanner to check if audio streaming is requested."""
    return _audio_request


async def send_audio_chunk(frequency_hz: float, audio_bytes: bytes) -> None:
    """Send demodulated audio to subscribed WebSocket clients."""
    global _audio_clients
    for ws, sub_freq in list(_audio_clients.items()):
        if sub_freq is not None and abs(sub_freq - frequency_hz) < 5000:
            try:
                await ws.send_bytes(audio_bytes)
            except Exception:
                _audio_clients.pop(ws, None)


@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    global _audio_clients
    await websocket.accept()
    _audio_clients[websocket] = None
    logger.debug("Audio WebSocket client connected")

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "subscribe":
                freq = data.get("frequency_hz", 0)
                modulation = data.get("modulation")
                _audio_clients[websocket] = freq
                _audio_request["frequency_hz"] = freq
                _audio_request["active"] = True
                _audio_request["modulation"] = modulation
                logger.debug("Audio subscribe: %.3f MHz (mod=%s)", freq / 1e6, modulation)
                await websocket.send_json({"type": "subscribed", "frequency_hz": freq})
            elif data.get("type") == "unsubscribe":
                _audio_clients[websocket] = None
                # Check if any client still subscribed
                if not any(f is not None for f in _audio_clients.values()):
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
        if not any(f is not None for f in _audio_clients.values()):
            _audio_request["frequency_hz"] = None
            _audio_request["active"] = False
            _audio_request["modulation"] = None
        logger.debug("Audio WebSocket client disconnected")
