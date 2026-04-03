import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_audio_clients: dict[WebSocket, float | None] = {}


async def send_audio_chunk(frequency_hz, audio_bytes):
    for ws, sub_freq in list(_audio_clients.items()):
        if sub_freq is not None and abs(sub_freq - frequency_hz) < 1000:
            try:
                await ws.send_bytes(audio_bytes)
            except Exception:
                _audio_clients.pop(ws, None)


@router.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    await websocket.accept()
    _audio_clients[websocket] = None
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "subscribe":
                freq = data.get("frequency_hz", 0)
                _audio_clients[websocket] = freq
                await websocket.send_json({"type": "subscribed", "frequency_hz": freq})
            elif data.get("type") == "unsubscribe":
                _audio_clients[websocket] = None
                await websocket.send_json({"type": "unsubscribed"})
    except WebSocketDisconnect:
        pass
    finally:
        _audio_clients.pop(websocket, None)
