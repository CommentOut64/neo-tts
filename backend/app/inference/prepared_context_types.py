from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Protocol


if TYPE_CHECKING:
    from backend.app.inference.block_adapter_types import BlockRenderRequest, BlockRenderResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PreparedContextDescriptor:
    adapter_id: str
    cache_key: str
    debug_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedContextEntry:
    adapter_id: str
    cache_key: str
    payload: Any
    estimated_bytes: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    last_access_at: datetime = field(default_factory=_utcnow)
    debug_summary: dict[str, Any] = field(default_factory=dict)
    dispose: Callable[[], None] | None = None

    def touch(self) -> None:
        self.last_access_at = _utcnow()


@dataclass(frozen=True)
class PreparedContextStats:
    session_count: int
    entry_count: int
    total_estimated_bytes: int


class PreparedContextCapableAdapter(Protocol):
    def describe_prepared_contexts(self, request: "BlockRenderRequest") -> list[PreparedContextDescriptor]:
        ...

    def build_prepared_context(
        self,
        request: "BlockRenderRequest",
        descriptor: PreparedContextDescriptor,
    ) -> PreparedContextEntry:
        ...

    def render_block(
        self,
        request: "BlockRenderRequest",
        *,
        prepared_contexts: dict[str, PreparedContextEntry] | None = None,
    ) -> "BlockRenderResult":
        ...
