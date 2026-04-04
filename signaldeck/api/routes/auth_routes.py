from fastapi import APIRouter, HTTPException, Request
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


def _require_auth(request: Request):
    """Verify Bearer token from request. Raises 401 if invalid or missing.

    Auth routes are excluded from AuthMiddleware, so protected auth endpoints
    must validate the token themselves.
    """
    mgr = get_auth_manager()
    if not mgr:
        raise HTTPException(status_code=404, detail="Auth not configured")
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header[7:]
    if not mgr.verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return mgr


from signaldeck.api.auth import generate_api_token


class ToggleAuthRequest(BaseModel):
    enabled: bool


@router.get("/token")
async def get_token(request: Request):
    """Return the current API token. Requires authentication."""
    mgr = _require_auth(request)
    return {"api_token": mgr.api_token}


@router.post("/regenerate-token")
async def regenerate_token(request: Request):
    """Generate a new API token. Invalidates the old one."""
    mgr = _require_auth(request)
    mgr.api_token = generate_api_token()
    mgr._save()
    return {"api_token": mgr.api_token}


@router.post("/toggle")
async def toggle_auth(data: ToggleAuthRequest):
    """Enable or disable authentication."""
    from signaldeck.api.server import get_config, _state
    config = get_config()
    config.setdefault("auth", {})["enabled"] = data.enabled

    if data.enabled and "auth" not in _state:
        from signaldeck.api.auth import AuthManager
        cred_path = config.get("auth", {}).get("credentials_path", "config/credentials.yaml")
        mgr = AuthManager(credentials_path=cred_path)
        mgr.initialize()
        _state["auth"] = mgr
    elif not data.enabled:
        _state.pop("auth", None)

    return {"enabled": data.enabled}
