"""FastAPI application setup."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.storage import Storage
from src.config import Config


def create_app(config: Config, storage: Storage) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(title="Dog Detector")

    # Store dependencies
    app.state.config = config
    app.state.storage = storage

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=templates_dir)

    # Import and include routes
    from src.web.routes import router
    app.include_router(router)

    return app
