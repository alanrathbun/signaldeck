import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from signaldeck import __version__
from signaldeck.storage.database import Database

logger = logging.getLogger(__name__)
_state = {}

def get_db() -> Database:
    return _state["db"]

def get_config() -> dict:
    return _state["config"]

def get_auth_manager():
    return _state.get("auth")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth_mgr = _state.get("auth")
        if auth_mgr is None:
            return await call_next(request)

        path = request.url.path

        # Public paths
        if path in ("/api/health",) or path.startswith("/api/auth/") or path.startswith("/ws/"):
            return await call_next(request)

        # Non-API paths (static files)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Check bearer token
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if auth_mgr.verify_token(token):
                return await call_next(request)

        # Check session cookie
        session = request.cookies.get("session_token")
        if session and auth_mgr.verify_token(session):
            return await call_next(request)

        return JSONResponse({"detail": "Not authenticated"}, status_code=401)


def create_app(config: dict, shared_db: Database | None = None) -> FastAPI:
    """Create the FastAPI application.

    Args:
        config: Application configuration dict.
        shared_db: Optional pre-initialized Database instance to share with
                   the scanner engine. If provided, the server won't create
                   its own connection or close it on shutdown.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if shared_db:
            _state["db"] = shared_db
            owns_db = False
        else:
            db_path = config["storage"]["database_path"]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            db = Database(db_path)
            await db.initialize()
            _state["db"] = db
            owns_db = True

        _state["config"] = config

        # Initialize auth if enabled
        auth_config = config.get("auth", {})
        if auth_config.get("enabled", False):
            from signaldeck.api.auth import AuthManager
            cred_path = auth_config.get("credentials_path", "config/credentials.yaml")
            mgr = AuthManager(credentials_path=cred_path)
            mgr.initialize()
            _state["auth"] = mgr
            logger.info("Authentication enabled")

        logger.info("API server started")
        yield
        if owns_db:
            await _state["db"].close()
        _state.clear()

    app = FastAPI(title="SignalDeck", version=__version__, lifespan=lifespan)

    app.add_middleware(AuthMiddleware)

    from signaldeck.api.routes.scanner import router as scanner_router
    from signaldeck.api.routes.signals import router as signals_router
    from signaldeck.api.routes.bookmarks import router as bookmarks_router
    from signaldeck.api.routes.recordings import router as recordings_router
    from signaldeck.api.routes.analytics import router as analytics_router
    from signaldeck.api.routes.auth_routes import router as auth_router
    from signaldeck.api.routes.logs import router as logs_router
    from signaldeck.api.routes.process import router as process_router

    app.include_router(scanner_router, prefix="/api")
    app.include_router(signals_router, prefix="/api")
    app.include_router(bookmarks_router, prefix="/api")
    app.include_router(recordings_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(process_router, prefix="/api")

    from signaldeck.api.websocket.live_signals import router as ws_signals_router
    from signaldeck.api.websocket.audio_stream import router as ws_audio_router
    from signaldeck.api.websocket.waterfall import router as ws_waterfall_router

    app.include_router(ws_signals_router)
    app.include_router(ws_audio_router)
    app.include_router(ws_waterfall_router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    web_dir = Path(__file__).parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")

    return app
