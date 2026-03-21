from fastapi import APIRouter

from backend.app.api.routers.health import router as health_router
from backend.app.api.routers.tts import router as tts_router
from backend.app.api.routers.voices import router as voices_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(voices_router)
api_router.include_router(tts_router)
