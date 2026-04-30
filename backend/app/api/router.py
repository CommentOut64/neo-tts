from fastapi import APIRouter

from backend.app.api.routers.edit_session import router as edit_session_router
from backend.app.api.routers.health import router as health_router
from backend.app.api.routers.system import router as system_router
from backend.app.api.routers.tts import router as tts_router
from backend.app.api.routers.tts_registry import router as tts_registry_router
from backend.app.api.routers.voices import router as voices_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(system_router)
api_router.include_router(tts_registry_router)
api_router.include_router(voices_router)
api_router.include_router(tts_router)
api_router.include_router(edit_session_router)
