from fastapi import APIRouter

router = APIRouter()

@router.get("/recordings")
async def list_recordings():
    return []
