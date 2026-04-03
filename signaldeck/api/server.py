import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from signaldeck import __version__
from signaldeck.storage.database import Database

logger = logging.getLogger(__name__)
_state = {}

def get_db() -> Database:
    return _state["db"]

def get_config() -> dict:
    return _state["config"]

def create_app(config: dict) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = config["storage"]["database_path"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = Database(db_path)
        await db.initialize()
        _state["db"] = db
        _state["config"] = config
        logger.info("API server started, database at %s", db_path)
        yield
        await db.close()
        _state.clear()

    app = FastAPI(title="SignalDeck", version=__version__, lifespan=lifespan)

    from signaldeck.api.routes.scanner import router as scanner_router
    from signaldeck.api.routes.signals import router as signals_router
    from signaldeck.api.routes.bookmarks import router as bookmarks_router
    from signaldeck.api.routes.recordings import router as recordings_router
    from signaldeck.api.routes.analytics import router as analytics_router

    app.include_router(scanner_router, prefix="/api")
    app.include_router(signals_router, prefix="/api")
    app.include_router(bookmarks_router, prefix="/api")
    app.include_router(recordings_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")

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
