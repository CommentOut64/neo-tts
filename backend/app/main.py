from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.core.exceptions import register_exception_handlers
from backend.app.core.lifespan import app_lifespan
from backend.app.core.logging import configure_logging
from backend.app.core.settings import AppSettings, get_settings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(project_root=app_settings.project_root)
    app = FastAPI(title="GPT-SoVITS Rebuild Backend", lifespan=app_lifespan)
    app.state.settings = app_settings
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
