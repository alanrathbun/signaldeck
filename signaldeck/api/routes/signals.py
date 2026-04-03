from fastapi import APIRouter, Query
from signaldeck.api.server import get_db

router = APIRouter()

@router.get("/signals")
async def list_signals():
    db = get_db()
    signals = await db.get_all_signals()
    return [
        {
            "frequency_hz": s.frequency,
            "frequency_mhz": s.frequency / 1_000_000,
            "bandwidth_hz": s.bandwidth,
            "modulation": s.modulation,
            "protocol": s.protocol,
            "first_seen": s.first_seen.isoformat(),
            "last_seen": s.last_seen.isoformat(),
            "hit_count": s.hit_count,
            "avg_strength": s.avg_strength,
            "confidence": s.confidence,
        }
        for s in signals
    ]

@router.get("/activity")
async def list_activity(limit: int = Query(default=50, ge=1, le=1000)):
    db = get_db()
    entries = await db.get_recent_activity(limit=limit)
    return [
        {
            "id": e.id, "signal_id": e.signal_id,
            "timestamp": e.timestamp.isoformat(), "duration": e.duration,
            "strength": e.strength, "decoder_used": e.decoder_used,
            "result_type": e.result_type, "summary": e.summary,
            "audio_path": e.audio_path,
        }
        for e in entries
    ]
