import asyncio
import logging
from typing import Any
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from signaldeck.api.websocket._auth import ws_authorized

logger = logging.getLogger(__name__)
router = APIRouter()
_waterfall_clients: set[WebSocket] = set()


def fft_broadcast(center_freq_hz, sample_rate, power_db):
    num_bins = len(power_db)
    half_bw = sample_rate / 2
    return {
        "type": "fft",
        "center_freq_hz": center_freq_hz,
        "center_freq_mhz": round(center_freq_hz / 1e6, 4),
        "sample_rate": sample_rate,
        "data": [round(float(v), 1) for v in power_db],
        "freq_start": center_freq_hz - half_bw,
        "freq_end": center_freq_hz + half_bw,
    }


async def broadcast_fft(message: dict):
    global _waterfall_clients
    disconnected = set()
    for ws in list(_waterfall_clients):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)
    _waterfall_clients -= disconnected


@router.websocket("/ws/waterfall")
async def ws_waterfall(websocket: WebSocket):
    if not await ws_authorized(websocket):
        await websocket.close(code=1008)
        return
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
