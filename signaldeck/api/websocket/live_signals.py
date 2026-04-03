import asyncio
import logging
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_clients: set[WebSocket] = set()


def signal_broadcast(frequency_hz, bandwidth_hz, power, modulation="unknown", protocol=None):
    return {
        "type": "signal",
        "frequency": frequency_hz,
        "frequency_hz": frequency_hz,
        "frequency_mhz": round(frequency_hz / 1e6, 4),
        "bandwidth": bandwidth_hz,
        "bandwidth_hz": bandwidth_hz,
        "power": power,
        "modulation": modulation,
        "protocol": protocol,
    }


async def broadcast(message: dict):
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)
    _clients -= disconnected


@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
