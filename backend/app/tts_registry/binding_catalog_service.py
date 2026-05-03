from __future__ import annotations

from backend.app.tts_registry.types import BindingCatalogResponse
from backend.app.tts_registry.workspace_service import WorkspaceService


class BindingCatalogService:
    def __init__(self, *, workspace_service: WorkspaceService) -> None:
        self._workspace_service = workspace_service

    def get_catalog(
        self,
        *,
        workspace_id: str | None = None,
        adapter_id: str | None = None,
        family_id: str | None = None,
        include_disabled: bool = False,
    ) -> BindingCatalogResponse:
        return self._workspace_service.build_binding_catalog(
            workspace_id=workspace_id,
            adapter_id=adapter_id,
            family_id=family_id,
            include_disabled=include_disabled,
        )
