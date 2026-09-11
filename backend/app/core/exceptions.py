from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.core.logging import get_logger
from backend.app.inference.runtime_errors import map_runtime_error
from runtime.gsv import RuntimeFailure


class EditSessionNotFoundError(LookupError):
    pass


class ActiveRenderJobConflictError(RuntimeError):
    pass


class SnapshotStateError(RuntimeError):
    pass


class AssetNotFoundError(LookupError):
    pass


class AssetExpiredError(RuntimeError):
    pass


class InvalidRangeError(RuntimeError):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RuntimeFailure)
    async def _gsv_runtime_error_handler(_: Request, exc: RuntimeFailure) -> JSONResponse:
        status, payload = map_runtime_error(exc.info)
        get_logger("gsv_runtime").opt(exception=exc).error(
            "Runtime request failed request_id={} code={} checkpoint={}",
            payload["error"]["request_id"], exc.info.error_code, exc.info.checkpoint,
        )
        return JSONResponse(status_code=status, content=payload)

    @app.exception_handler(LookupError)
    async def _lookup_error_handler(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AssetExpiredError)
    async def _asset_expired_handler(_: Request, exc: AssetExpiredError) -> JSONResponse:
        return JSONResponse(status_code=410, content={"detail": str(exc)})

    @app.exception_handler(InvalidRangeError)
    async def _invalid_range_handler(_: Request, exc: InvalidRangeError) -> JSONResponse:
        return JSONResponse(status_code=416, content={"detail": str(exc)})

    @app.exception_handler(ActiveRenderJobConflictError)
    async def _runtime_error_handler(_: Request, exc: ActiveRenderJobConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(SnapshotStateError)
    async def _snapshot_state_error_handler(_: Request, exc: SnapshotStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
