"""FastAPI application setup."""

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.storage import Storage
from src.config import Config, SettingsStore
from src.deterrence import DeterrenceController
from src.web.auth import create_login_manager, request_is_authenticated


PUBLIC_EXACT_PATHS = {"/login", "/api/auth/login", "/health"}
PUBLIC_PREFIXES = ("/static/",)


def create_app(
    config: Config,
    storage: Storage,
    settings_store: SettingsStore | None = None,
    generated_auth_credentials: dict[str, str] | None = None,
    deterrence_controller: DeterrenceController | None = None,
) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(title="Doggy Detector")

    # Store dependencies
    app.state.config = config
    app.state.storage = storage
    app.state.settings_store = settings_store or SettingsStore(storage.data_dir)
    app.state.generated_auth_credentials = generated_auth_credentials
    app.state.deterrence_controller = deterrence_controller or DeterrenceController(
        config.deterrence,
        storage,
    )
    app.state.project_dir = Path(__file__).resolve().parents[2]

    created_credentials = app.state.settings_store.ensure_auth_credentials()
    if app.state.generated_auth_credentials is None:
        app.state.generated_auth_credentials = created_credentials
    app.state.auth_manager = create_login_manager(app.state.settings_store)

    # Static files
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    app.state.templates = Jinja2Templates(directory=templates_dir)

    # Import and include routes
    from src.web.routes import router
    app.include_router(router)

    @app.middleware("http")
    async def require_dashboard_auth(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_EXACT_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        if await request_is_authenticated(request):
            return await call_next(request)

        if path == "/" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=303)

        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    return app
