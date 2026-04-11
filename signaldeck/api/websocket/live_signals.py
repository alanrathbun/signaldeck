import asyncio
import logging
import time
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_clients: set[WebSocket] = set()

# Throttle: track last broadcast time per frequency (rounded to nearest kHz)
_last_broadcast: dict[int, float] = {}
_BROADCAST_INTERVAL_S = 2.0  # minimum seconds between updates for the same frequency


def signal_broadcast(frequency_hz, bandwidth_hz, power, modulation="unknown", protocol=None, **extra):
    msg = {
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
    msg.update(extra)
    return msg


def signal_batch_broadcast(signals: list[dict]):
    return {
        "type": "signal_batch",
        "signals": signals,
    }


async def broadcast(message: dict):
    global _clients

    if message.get("type") == "signal_batch":
        disconnected = set()
        for ws in list(_clients):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        _clients -= disconnected
        return

    # Throttle per-frequency updates to avoid overwhelming the UI
    freq_key = int(message.get("frequency_hz", 0) / 1000)  # round to kHz
    now = time.monotonic()
    last = _last_broadcast.get(freq_key, 0)
    if now - last < _BROADCAST_INTERVAL_S:
        return
    _last_broadcast[freq_key] = now
    logger.debug("Broadcasting signal %.3f MHz to %d client(s)", message.get("frequency_mhz", 0), len(_clients))

    # Prune old entries periodically
    if len(_last_broadcast) > 5000:
        cutoff = now - 60
        _last_broadcast.clear()

    disconnected = set()
    for ws in list(_clients):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)
    _clients -= disconnected


@router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    logger.debug("WebSocket client connected (%d total)", len(_clients))
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.debug("WebSocket client disconnected (%d remaining)", len(_clients))
