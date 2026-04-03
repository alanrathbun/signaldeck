from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from signaldeck.api.server import get_db
from signaldeck.storage.models import Bookmark

router = APIRouter(tags=["bookmarks"])

class BookmarkCreate(BaseModel):
    frequency_hz: float
    label: str
    modulation: str = "FM"
    decoder: str | None = None
    priority: int = 3
    camp_on_active: bool = False
    notes: str = ""

@router.get("/bookmarks")
async def list_bookmarks():
    db = get_db()
    bookmarks = await db.get_all_bookmarks()
    return [{"id": b.id, "frequency_hz": b.frequency, "frequency_mhz": round(b.frequency / 1e6, 4),
             "label": b.label, "modulation": b.modulation, "decoder": b.decoder,
             "priority": b.priority, "camp_on_active": b.camp_on_active,
             "notes": b.notes, "created_at": b.created_at.isoformat()} for b in bookmarks]

@router.post("/bookmarks", status_code=201)
async def create_bookmark(data: BookmarkCreate):
    db = get_db()
    bookmark = Bookmark(frequency=data.frequency_hz, label=data.label, modulation=data.modulation,
        decoder=data.decoder, priority=data.priority, camp_on_active=data.camp_on_active,
        notes=data.notes, created_at=datetime.now(timezone.utc))
    bk_id = await db.insert_bookmark(bookmark)
    return {"id": bk_id, "label": data.label}

@router.delete("/bookmarks/{bookmark_id}")
async def delete_bookmark(bookmark_id: int):
    db = get_db()
    deleted = await db.delete_bookmark(bookmark_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"deleted": True}
