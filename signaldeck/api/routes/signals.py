from fastapi import APIRouter
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
