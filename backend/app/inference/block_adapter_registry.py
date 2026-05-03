from __future__ import annotations

from backend.app.inference.adapter_definition import AdapterDefinition
from backend.app.inference.block_adapter_errors import BlockAdapterError


class AdapterRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, AdapterDefinition] = {}

    def register(self, adapter_definition: AdapterDefinition) -> None:
        adapter_id = adapter_definition.adapter_id
        if adapter_id in self._definitions:
            raise ValueError(f"Adapter '{adapter_id}' is already registered.")
        self._definitions[adapter_id] = adapter_definition

    def get(self, adapter_id: str) -> AdapterDefinition | None:
        return self._definitions.get(adapter_id)

    def require(self, adapter_id: str) -> AdapterDefinition:
        adapter_definition = self.get(adapter_id)
        if adapter_definition is None:
            raise BlockAdapterError(
                error_code="adapter_not_installed",
                message=f"Adapter '{adapter_id}' is not installed.",
                details={"adapter_id": adapter_id},
            )
        return adapter_definition

    def list_adapters(self) -> list[AdapterDefinition]:
        return list(self._definitions.values())

    @staticmethod
    def build_model_required_error(*, adapter_id: str | None = None) -> BlockAdapterError:
        details = {"adapter_id": adapter_id} if adapter_id else {}
        return BlockAdapterError(
            error_code="model_required",
            message="当前请求缺少可用模型绑定。",
            details=details,
        )
