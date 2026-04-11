from collections import Counter

from fastapi import APIRouter
from signaldeck.api.server import get_db

router = APIRouter()


@router.get("/analytics/summary")
async def analytics_summary():
    db = get_db()
    signals = await db.get_all_signals()
    activity = await db.get_recent_activity(limit=500)

    # Protocol/modulation distribution for pie chart
    protocol_counts = Counter()
    for s in signals:
        label = s.protocol or s.modulation or "unknown"
        protocol_counts[label] += s.hit_count

    # Hourly activity distribution for bar chart
    hourly_counts = Counter()
    for a in activity:
        hourly_counts[a.timestamp.hour] += 1
    # Fill all 24 hours
    hourly = {str(h): hourly_counts.get(h, 0) for h in range(24)}

    return {
        "total_signals": len(signals),
        "protocols": dict(protocol_counts),
        "protocol_counts": dict(protocol_counts),
        "hourly": hourly,
        "hourly_counts": hourly,
    }
