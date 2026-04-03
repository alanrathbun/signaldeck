from fastapi import APIRouter

router = APIRouter()

@router.get("/scanner/status")
async def scanner_status():
    return {"status": "idle", "mode": None, "active_devices": 0}
