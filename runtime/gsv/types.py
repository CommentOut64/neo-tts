from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .language import LanguageResolution


def _absolute(value: str | Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Runtime resources must use absolute paths: {value!r}")
    return str(path.resolve())


def _mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    resources_root: str
    device: str = "cpu"
    dtype: str = "float32"
    g2p_provider: str = "official"
    processing_revision: str = "s1"
    cache_budget: int = 0
    cnhubert_path: str | None = None
    bert_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "resources_root", _absolute(self.resources_root))
        if self.device not in {"cpu", "cuda", "auto"}:
            raise ValueError("device must be cpu, cuda, or auto")
        if self.g2p_provider != "official":
            raise ValueError("Only the official G2P provider is supported")
        if self.cache_budget < 0:
            raise ValueError("cache_budget cannot be negative")
        if self.dtype not in {"float32", "float16", "half"}:
            raise ValueError("dtype must be float32 or float16")
        for name in ("cnhubert_path", "bert_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _absolute(value))


@dataclass(frozen=True, slots=True)
class ModelSpec:
    gpt_path: str
    sovits_path: str
    config_path: str | None = None
    model_revision: str = ""
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gpt_path", _absolute(self.gpt_path))
        object.__setattr__(self, "sovits_path", _absolute(self.sovits_path))
        if self.config_path:
            object.__setattr__(self, "config_path", _absolute(self.config_path))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    gpt_revision: str
    sovits_revision: str
    sample_rate: int
    quantizer: str = ""
    device: str = "cpu"
    dtype: str = "float32"
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelLease:
    lease_id: str
    spec: ModelSpec
    identity: ModelIdentity
    backend: Any = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Control:
    request_id: str | None = None
    job_id: str | None = None
    segment_id: str | None = None
    edge_id: str | None = None
    should_cancel: Any = field(default=None, repr=False, compare=False)
    attempt: int | None = None

    def cancelled(self) -> bool:
        return callable(self.should_cancel) and bool(self.should_cancel())


@dataclass(frozen=True, slots=True)
class ReferenceRequest:
    audio_path: str
    text: str
    language: str
    identity: str = ""
    content_revision: str = ""
    language_resolution: LanguageResolution | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "audio_path", _absolute(self.audio_path))


@dataclass(frozen=True, slots=True)
class ReferenceFeatures:
    reference_id: str
    content_revision: str
    model_revision: str
    sample_rate: int
    sovits_revision: str = ""
    processing_revision: str = ""
    semantic_tokens: tuple[int, ...] = ()
    phones: tuple[int, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    payload: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_tokens", tuple(self.semantic_tokens))
        object.__setattr__(self, "phones", tuple(self.phones))
        object.__setattr__(self, "metadata", _mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class RenderConfig:
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0
    noise_scale: float = 0.35
    margin_frame_count: int = 6
    boundary_overlap_frame_count: int = 6
    boundary_padding_frame_count: int = 4
    boundary_result_frame_count: int = 6


@dataclass(frozen=True, slots=True)
class SegmentRequest:
    segment_id: str
    text: str
    language: str = "auto"
    render_version: int = 1
    terminal_raw: str = ""
    terminal_closer_suffix: str = ""
    terminal_source: str = "synthetic"
    language_resolution: LanguageResolution | None = None


@dataclass(frozen=True, slots=True)
class BoundaryRequest:
    edge_id: str
    left_segment_id: str
    right_segment_id: str
    edge_version: int = 1
    strategy: str = "latent_overlap_then_equal_power_crossfade"
    effective_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentResult:
    segment_id: str
    render_version: int
    sample_rate: int
    audio: Any
    frame_count: int = 0
    phones: tuple[int, ...] = ()
    semantic: tuple[int, ...] = ()
    left_margin_audio: Any = None
    right_margin_audio: Any = None
    trace: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "phones", tuple(self.phones))
        object.__setattr__(self, "semantic", tuple(self.semantic))
        object.__setattr__(self, "trace", _mapping(self.trace))


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    edge_id: str
    left_segment_id: str
    right_segment_id: str
    edge_version: int
    sample_rate: int
    audio: Any
    strategy: str
    trace: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", _mapping(self.trace))


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    text: str
    reference: ReferenceRequest
    config: RenderConfig = field(default_factory=RenderConfig)
    language: str = "auto"
    model_spec: ModelSpec | None = None
    language_resolution: LanguageResolution | None = None


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    sample_rate: int
    audio: Any
    trace: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", _mapping(self.trace))


@dataclass(frozen=True, slots=True)
class RuntimeDescription:
    name: str
    version: str
    processing_revision: str
    capabilities: tuple[str, ...]
    device: str
    dtype: str
