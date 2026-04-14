from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.core.exceptions import register_exception_handlers
from backend.app.core.lifespan import app_lifespan
from backend.app.core.logging import configure_logging
from backend.app.core.settings import AppSettings, get_settings


def _mount_frontend_spa(app: FastAPI, frontend_dir: Path) -> None:
    """非开发模式下，由后端托管前端 SPA 静态资源。

    挂载顺序在所有 API 路由之后，确保 /health、/v1/* 等 API 路由优先匹配。
    """
    assets_dir = frontend_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    index_html = frontend_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # 请求路径在 frontend-dist/ 下对应实际文件时直接返回（如 512.ico）
        candidate = (frontend_dir / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(frontend_dir.resolve()):
            return FileResponse(str(candidate))
        # 否则返回 index.html，由前端 Vue Router 处理 SPA 路由
        return FileResponse(str(index_html))


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(project_root=app_settings.project_root)
    app = FastAPI(title="GPT-SoVITS Rebuild Backend", lifespan=app_lifespan)
    app.state.settings = app_settings
    register_exception_handlers(app)
    app.include_router(api_router)

    if app_settings.distribution_kind != "development":
        frontend_dir = app_settings.resources_root / "frontend-dist"
        if frontend_dir.is_dir():
            _mount_frontend_spa(app, frontend_dir)

    return app


app = create_app()
