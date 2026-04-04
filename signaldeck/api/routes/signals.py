from pathlib import Path

from fastapi import APIRouter, Query

from signaldeck.api.server import get_config, get_db

router = APIRouter()

@router.get("/signals/rds/{frequency_hz}")
async def get_rds_data(frequency_hz: int):
    """Return accumulated RDS metadata for a specific frequency."""
    db = get_db()
    rds = await db.get_rds_for_frequency(float(frequency_hz))
    return {"frequency_hz": frequency_hz, "rds": rds}

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

    # Enrich with RDS data for FM signals
    for s in signals:
        freq_key = str(int(s.frequency))
        if freq_key in result and s.protocol == "broadcast_fm":
            rds = await db.get_rds_for_frequency(s.frequency)
            if rds:
                result[freq_key]["rds"] = rds

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


@router.delete("/data/signals")
async def clear_signals():
    db = get_db()
    await db.clear_signals()
    return {"status": "cleared", "table": "signals"}


@router.delete("/data/activity")
async def clear_activity():
    db = get_db()
    await db.clear_activity()
    return {"status": "cleared", "table": "activity_log"}


@router.delete("/data/bookmarks")
async def clear_bookmarks():
    db = get_db()
    await db.clear_bookmarks()
    return {"status": "cleared", "table": "bookmarks"}


@router.delete("/data/recordings")
async def clear_recordings():
    db = get_db()
    await db.clear_recordings()
    config = get_config()
    rec_dir = Path(config.get("audio", {}).get("recording_dir", "data/recordings"))
    deleted_files = 0
    if rec_dir.exists():
        for f in rec_dir.glob("*.wav"):
            f.unlink()
            deleted_files += 1
    return {"status": "cleared", "table": "recordings", "files_deleted": deleted_files}


@router.delete("/data/all")
async def clear_all_data():
    db = get_db()
    await db.clear_all()
    config = get_config()
    rec_dir = Path(config.get("audio", {}).get("recording_dir", "data/recordings"))
    if rec_dir.exists():
        for f in rec_dir.glob("*.wav"):
            f.unlink()
    return {"status": "cleared", "table": "all"}
