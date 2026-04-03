import asyncio
import logging
from typing import Any
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_waterfall_clients: set[WebSocket] = set()


def fft_broadcast(center_freq_hz, sample_rate, power_db):
    return {
        "type": "fft",
        "center_freq_hz": center_freq_hz,
        "center_freq_mhz": round(center_freq_hz / 1e6, 4),
        "sample_rate": sample_rate,
        "power_db": [round(float(v), 1) for v in power_db],
    }


async def broadcast_fft(message: dict):
    disconnected = set()
    for ws in _waterfall_clients:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)
    _waterfall_clients -= disconnected


@router.websocket("/ws/waterfall")
async def ws_waterfall(websocket: WebSocket):
    await websocket.accept()
    _waterfall_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _waterfall_clients.discard(websocket)
