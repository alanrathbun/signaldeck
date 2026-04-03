from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from signaldeck.api.server import get_auth_manager

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    current_password: str
    new_password: str


@router.post("/login")
async def login(data: LoginRequest):
    mgr = get_auth_manager()
    if not mgr or not mgr.verify_login(data.username, data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session_token = mgr.create_session_token()
    return {
        "session_token": session_token,
        "api_token": mgr.api_token,
        "username": data.username,
    }


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest):
    mgr = get_auth_manager()
    if not mgr or not mgr.verify_login(data.username, data.current_password):
        raise HTTPException(status_code=401, detail="Invalid current credentials")

    mgr.change_password(data.username, data.new_password)
    return {"status": "password_changed"}
