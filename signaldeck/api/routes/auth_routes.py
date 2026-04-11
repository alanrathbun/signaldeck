from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from signaldeck.api.server import get_auth_manager, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    current_password: str
    new_password: str


@router.post("/login")
async def login(data: LoginRequest, request: Request, response: Response):
    mgr = get_auth_manager()
    if not mgr or not mgr.verify_login(data.username, data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    db = get_db()
    user_agent = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    raw_token = await mgr.create_remember_token(
        db, user_agent=user_agent, ip=ip, label=None
    )

    # Determine cookie Max-Age from config.
    from signaldeck.api.server import get_config
    cfg = get_config() or {}
    days = cfg.get("auth", {}).get("remember_token_days")
    if isinstance(days, int) and days > 0:
        max_age = days * 86400
    else:
        max_age = 315360000  # 10 years — "forever" for browsers

    response.set_cookie(
        key="sd_remember",
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return {
        "username": data.username,
        "remember_token": raw_token,
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
    """Enable or disable authentication.

    On the very first enable (when credentials.yaml is being created),
    returns the generated admin password in first_run_password so the
    frontend can show it exactly once. Subsequent toggles do not return
    a password (the credentials already exist).
    """
    from signaldeck.api.server import get_config, _state
    from pathlib import Path
    config = get_config()
    config.setdefault("auth", {})["enabled"] = data.enabled

    first_run_password = None
    if data.enabled:
        from signaldeck.api.auth import AuthManager
        cred_path = config.get("auth", {}).get("credentials_path", "config/credentials.yaml")
        cred_file_existed = Path(cred_path).exists()

        if "auth" not in _state:
            mgr = AuthManager(credentials_path=cred_path)
            mgr.initialize()
            _state["auth"] = mgr
        else:
            mgr = _state["auth"]

        if not cred_file_existed and mgr._initial_password is not None:
            first_run_password = mgr._initial_password
    else:
        _state.pop("auth", None)

    response_body = {"enabled": data.enabled}
    if first_run_password is not None:
        response_body["first_run_password"] = first_run_password
    return response_body
