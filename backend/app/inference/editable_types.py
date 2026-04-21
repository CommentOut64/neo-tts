from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

import numpy as np
import torch

from backend.app.inference.text_processing import compute_effective_margin_frame_count


@dataclass(frozen=True)
class ReferenceContext:
    reference_context_id: str
    voice_id: str
    model_id: str
    reference_audio_path: str
    reference_text: str
    reference_language: str
    reference_semantic_tokens: np.ndarray | None
    reference_spectrogram: torch.Tensor
    reference_speaker_embedding: torch.Tensor
    inference_config_fingerprint: str
    inference_config: dict[str, Any] = field(default_factory=dict)
    prompt_phones: list[int] = field(default_factory=list)
    prompt_bert: torch.Tensor | None = None
    prompt_norm_text: str = ""
    backend_cache_key: tuple[str, str] | None = None
    reference_scope: str = ""
    reference_identity: str = ""
    reference_audio_fingerprint: str = ""
    reference_text_fingerprint: str = ""


@dataclass(frozen=True)
class ResolvedVoiceBinding:
    voice_binding_id: str
    voice_id: str
    model_key: str
    gpt_path: str | None = None
    sovits_path: str | None = None
    speaker_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedRenderContext:
    voice_id: str
    model_key: str
    reference_audio_path: str
    reference_text: str
    reference_language: str
    reference_scope: str = ""
    reference_identity: str = ""
    reference_audio_fingerprint: str = ""
    reference_text_fingerprint: str = ""
    speed: float = 1.0
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    noise_scale: float = 0.35
    resolved_voice_binding: ResolvedVoiceBinding | None = None
    render_profile_id: str | None = None
    render_profile_fingerprint: str = ""


@dataclass(frozen=True)
class SegmentRenderAssetPayload:
    render_asset_id: str
    segment_id: str
    render_version: int
    semantic_tokens: list[int]
    phone_ids: list[int]
    decoder_frame_count: int
    audio_sample_count: int
    left_margin_sample_count: int
    core_sample_count: int
    right_margin_sample_count: int
    left_margin_audio: np.ndarray
    core_audio: np.ndarray
    right_margin_audio: np.ndarray
    trace: dict[str, Any] | None


@dataclass(frozen=True)
class BoundaryAssetPayload:
    boundary_asset_id: str
    left_segment_id: str
    left_render_version: int
    right_segment_id: str
    right_render_version: int
    edge_version: int
    boundary_strategy: str
    boundary_sample_count: int
    boundary_audio: np.ndarray
    trace: dict[str, Any] | None


@dataclass(frozen=True)
class RenderBlock:
    block_id: str
    segment_ids: list[str]
    start_order_key: int
    end_order_key: int
    estimated_sample_count: int


@dataclass(frozen=True)
class SegmentCompositionEntry:
    segment_id: str
    audio_sample_span: tuple[int, int]
    order_key: int = 0
    render_asset_id: str | None = None


@dataclass(frozen=True)
class EdgeCompositionEntry:
    edge_id: str
    left_segment_id: str
    right_segment_id: str
    boundary_strategy: str
    effective_boundary_strategy: str
    pause_duration_seconds: float
    boundary_sample_span: tuple[int, int]
    pause_sample_span: tuple[int, int]


@dataclass(frozen=True)
class BlockMarkerEntry:
    marker_type: str
    sample: int
    related_id: str


@dataclass(frozen=True)
class BlockCompositionAssetPayload:
    block_id: str
    segment_ids: list[str]
    sample_rate: int
    audio: np.ndarray
    audio_sample_count: int
    segment_entries: list[SegmentCompositionEntry]
    block_asset_id: str = ""
    edge_entries: list[EdgeCompositionEntry] = field(default_factory=list)
    marker_entries: list[BlockMarkerEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.block_asset_id:
            object.__setattr__(self, "block_asset_id", self.block_id)


@dataclass(frozen=True)
class DocumentCompositionManifestPayload:
    composition_manifest_id: str
    document_id: str
    document_version: int
    sample_rate: int
    audio_sample_count: int
    playable_sample_span: tuple[int, int]
    block_ids: list[str]
    block_spans: dict[str, tuple[int, int]]
    segment_entries: list[SegmentCompositionEntry]
    audio: np.ndarray | None


@dataclass(frozen=True)
class PreviewPayload:
    preview_asset_id: str
    preview_kind: str
    sample_rate: int
    audio: np.ndarray


def fingerprint_inference_config(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def build_render_asset_id(*, segment_id: str, render_version: int, semantic_tokens: list[int], fingerprint: str) -> str:
    semantic_digest = hashlib.sha1(",".join(map(str, semantic_tokens)).encode("utf-8")).hexdigest()[:12]
    return f"{segment_id}-v{render_version}-{fingerprint[:8]}-{semantic_digest}"


def build_boundary_asset_id(
    *,
    left_segment_id: str,
    left_render_version: int,
    right_segment_id: str,
    right_render_version: int,
    edge_version: int,
    boundary_strategy: str,
) -> str:
    raw = "|".join(
        [
            left_segment_id,
            str(left_render_version),
            right_segment_id,
            str(right_render_version),
            str(edge_version),
            boundary_strategy,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return (
        f"{left_segment_id}-v{left_render_version}-"
        f"{right_segment_id}-v{right_render_version}-"
        f"e{edge_version}-{digest}"
    )


def split_segment_audio(
    *,
    audio: np.ndarray,
    encoder_frames: torch.Tensor,
    requested_margin_frame_count: int,
    generator_stride_samples: int,
    min_core_frame_count: int = 10,
) -> dict[str, Any]:
    decoder_frame_count = int(encoder_frames.shape[-1])
    effective_margin_frame_count = compute_effective_margin_frame_count(
        decoder_frame_count=decoder_frame_count,
        requested_margin_frame_count=requested_margin_frame_count,
        min_core_frame_count=min_core_frame_count,
    )
    margin_sample_count = effective_margin_frame_count * generator_stride_samples

    if effective_margin_frame_count == 0:
        return {
            "decoder_frame_count": decoder_frame_count,
            "left_margin_sample_count": 0,
            "core_sample_count": int(audio.shape[-1]),
            "right_margin_sample_count": 0,
            "left_margin_audio": np.zeros(0, dtype=np.float32),
            "core_audio": audio.astype(np.float32, copy=False),
            "right_margin_audio": np.zeros(0, dtype=np.float32),
            "left_margin_frames": [],
            "right_margin_frames": [],
        }

    left_margin_audio = audio[:margin_sample_count].astype(np.float32, copy=False)
    core_audio = audio[margin_sample_count:-margin_sample_count].astype(np.float32, copy=False)
    right_margin_audio = audio[-margin_sample_count:].astype(np.float32, copy=False)
    left_margin_frames_tensor = encoder_frames[..., :effective_margin_frame_count].detach().cpu().float()
    right_margin_frames_tensor = encoder_frames[..., -effective_margin_frame_count:].detach().cpu().float()
    if left_margin_frames_tensor.dim() > 1 and left_margin_frames_tensor.shape[0] == 1:
        left_margin_frames_tensor = left_margin_frames_tensor.squeeze(0)
    if right_margin_frames_tensor.dim() > 1 and right_margin_frames_tensor.shape[0] == 1:
        right_margin_frames_tensor = right_margin_frames_tensor.squeeze(0)
    if left_margin_frames_tensor.dim() > 1 and left_margin_frames_tensor.shape[0] == 1:
        left_margin_frames_tensor = left_margin_frames_tensor.squeeze(0)
    if right_margin_frames_tensor.dim() > 1 and right_margin_frames_tensor.shape[0] == 1:
        right_margin_frames_tensor = right_margin_frames_tensor.squeeze(0)
    left_margin_frames = left_margin_frames_tensor.tolist()
    right_margin_frames = right_margin_frames_tensor.tolist()

    return {
        "decoder_frame_count": decoder_frame_count,
        "left_margin_sample_count": int(left_margin_audio.shape[-1]),
        "core_sample_count": int(core_audio.shape[-1]),
        "right_margin_sample_count": int(right_margin_audio.shape[-1]),
        "left_margin_audio": left_margin_audio,
        "core_audio": core_audio,
        "right_margin_audio": right_margin_audio,
        "left_margin_frames": left_margin_frames,
        "right_margin_frames": right_margin_frames,
    }
