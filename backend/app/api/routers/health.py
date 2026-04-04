from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="健康检查",
    description="返回服务基础健康状态，适合前端启动时探活或部署环境健康检查。",
)
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
