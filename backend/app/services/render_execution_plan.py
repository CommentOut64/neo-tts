from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.inference.block_adapter_types import (
    AllowedDegradationPolicy,
    AllowedScopeEscalationPolicy,
    BlockRenderRequest,
    BoundaryContext,
    RenderScope,
    ReusableSourceAssetDescriptor,
    SegmentAlignmentMode,
)
from backend.app.inference.editable_types import RenderBlock


@dataclass(frozen=True)
class ScopeEscalationPolicy:
    requested_scope: RenderScope
    allowed_scopes: tuple[RenderScope, ...]


@dataclass(frozen=True)
class ResultDegradationPolicy:
    requested_mode: SegmentAlignmentMode
    allowed_modes: tuple[SegmentAlignmentMode, ...]


@dataclass(frozen=True)
class ExecutionBoundaryContext:
    boundary_context: BoundaryContext


@dataclass(frozen=True)
class ExecutionUnit:
    execution_unit_id: str
    formal_block_id: str
    request: BlockRenderRequest
    segment_ids: tuple[str, ...]
    boundary_contexts: tuple[ExecutionBoundaryContext, ...] = field(default_factory=tuple)
    reusable_source_assets: tuple[ReusableSourceAssetDescriptor, ...] = field(default_factory=tuple)
    scope_policy: ScopeEscalationPolicy | None = None
    degradation_policy: ResultDegradationPolicy | None = None


@dataclass(frozen=True)
class FormalBlockPlan:
    formal_block: RenderBlock
    execution_units: tuple[ExecutionUnit, ...]

    @property
    def formal_block_id(self) -> str:
        return self.formal_block.block_id


@dataclass(frozen=True)
class ExecutionPlan:
    formal_blocks: tuple[FormalBlockPlan, ...]

    def iter_execution_units(self) -> list[ExecutionUnit]:
        units: list[ExecutionUnit] = []
        for formal_block in self.formal_blocks:
            units.extend(formal_block.execution_units)
        return units


def build_scope_policy(request: BlockRenderRequest) -> ScopeEscalationPolicy:
    policy = request.allowed_scope_escalation
    return ScopeEscalationPolicy(
        requested_scope=policy.requested_scope,
        allowed_scopes=tuple(policy.allowed_scopes),
    )


def build_degradation_policy(request: BlockRenderRequest) -> ResultDegradationPolicy:
    policy = request.allowed_degradation
    return ResultDegradationPolicy(
        requested_mode=policy.requested_mode,
        allowed_modes=tuple(policy.allowed_modes),
    )


def normalize_scope_policy(
    *,
    render_scope: RenderScope,
    allowed_scopes: list[RenderScope] | None = None,
) -> AllowedScopeEscalationPolicy:
    scopes = list(allowed_scopes or [])
    if render_scope not in scopes:
        scopes.insert(0, render_scope)
    return AllowedScopeEscalationPolicy(
        requested_scope=render_scope,
        allowed_scopes=scopes,
    )


def normalize_degradation_policy(
    *,
    requested_mode: SegmentAlignmentMode = "exact",
    allowed_modes: list[SegmentAlignmentMode] | None = None,
) -> AllowedDegradationPolicy:
    modes = list(allowed_modes or [])
    if requested_mode not in modes:
        modes.insert(0, requested_mode)
    return AllowedDegradationPolicy(
        requested_mode=requested_mode,
        allowed_modes=modes,
    )
