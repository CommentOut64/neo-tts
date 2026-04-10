from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


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
