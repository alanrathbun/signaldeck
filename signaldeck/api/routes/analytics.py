from fastapi import APIRouter
from signaldeck.api.server import get_db

router = APIRouter()

@router.get("/analytics/summary")
async def analytics_summary():
    db = get_db()
    signals = await db.get_all_signals()
    return {
        "total_signals": len(signals),
        "total_bookmarks": 0,
        "total_recordings": 0,
    }
