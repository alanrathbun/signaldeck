from fastapi import APIRouter
from fastapi import Query

from signaldeck.api.server import get_db

router = APIRouter()

@router.get("/recordings")
async def list_recordings(limit: int = Query(default=200, ge=1, le=5000)):
    db = get_db()
    return await db.get_recordings(limit=limit)
