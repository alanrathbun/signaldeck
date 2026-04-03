from fastapi import APIRouter, Query
from signaldeck.api.server import get_db

router = APIRouter()

@router.get("/signals/enrichment")
async def signal_enrichment():
    """Return database signal data keyed by frequency (Hz) for frontend enrichment."""
    db = get_db()
    signals = await db.get_all_signals()
    activity = await db.get_recent_activity(limit=500)

    # Build activity lookup: signal_id -> most recent activity entry
    activity_by_signal: dict[int, dict] = {}
    for e in activity:
        if e.signal_id not in activity_by_signal:
            activity_by_signal[e.signal_id] = {
                "decoder": e.decoder_used,
                "type": e.result_type,
                "summary": e.summary,
                "timestamp": e.timestamp.isoformat(),
            }

    result = {}
    for s in signals:
        freq_key = str(int(s.frequency))
        entry = {
            "first_seen": s.first_seen.isoformat(),
            "last_seen": s.last_seen.isoformat(),
            "hit_count": s.hit_count,
            "confidence": s.confidence,
        }
        if s.id and s.id in activity_by_signal:
            entry["last_activity"] = activity_by_signal[s.id]
        else:
            entry["last_activity"] = None
        result[freq_key] = entry
    return result

@router.get("/signals")
async def list_signals(limit: int = Query(default=200, ge=1, le=5000),
                       sort: str = Query(default="hit_count")):
    db = get_db()
    signals = await db.get_all_signals()
    # Sort by requested field
    if sort == "hit_count":
        signals.sort(key=lambda s: s.hit_count, reverse=True)
    elif sort == "frequency":
        signals.sort(key=lambda s: s.frequency)
    elif sort == "last_seen":
        signals.sort(key=lambda s: s.last_seen, reverse=True)
    elif sort == "avg_strength":
        signals.sort(key=lambda s: s.avg_strength, reverse=True)
    signals = signals[:limit]
    return [
        {
            "id": s.id,
            "frequency": s.frequency,
            "frequency_hz": s.frequency,
            "frequency_mhz": round(s.frequency / 1e6, 4),
            "bandwidth": s.bandwidth,
            "bandwidth_hz": s.bandwidth,
            "modulation": s.modulation,
            "protocol": s.protocol,
            "first_seen": s.first_seen.isoformat(),
            "last_seen": s.last_seen.isoformat(),
            "hits": s.hit_count,
            "hit_count": s.hit_count,
            "power": s.avg_strength,
            "avg_strength": s.avg_strength,
            "confidence": s.confidence,
        }
        for s in signals
    ]

@router.get("/activity")
async def list_activity(limit: int = Query(default=50, ge=1, le=1000)):
    db = get_db()
    entries = await db.get_recent_activity(limit=limit)

    # Look up frequency for each activity entry from its signal
    results = []
    signal_cache: dict[int, float] = {}
    for e in entries:
        if e.signal_id not in signal_cache:
            sig = await db.get_signal_by_id(e.signal_id)
            signal_cache[e.signal_id] = sig.frequency if sig else 0
        freq = signal_cache[e.signal_id]
        results.append({
            "id": e.id, "signal_id": e.signal_id,
            "timestamp": e.timestamp.isoformat(), "duration": e.duration,
            "frequency": freq,
            "frequency_mhz": round(freq / 1e6, 4) if freq else None,
            "strength": e.strength, "decoder": e.decoder_used,
            "type": e.result_type, "summary": e.summary,
            "audio_path": e.audio_path,
        })
    return results
