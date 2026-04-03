from fastapi import APIRouter

router = APIRouter()

@router.get("/bookmarks")
async def list_bookmarks():
    return []

@router.post("/bookmarks")
async def create_bookmark():
    return {"status": "not implemented"}
