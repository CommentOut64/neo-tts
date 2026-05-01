from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.block_adapter_types import BlockRenderRequest, BlockRenderResult, SegmentOutput, SegmentSpan
from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BlockMarkerEntry,
    EdgeCompositionEntry,
    SegmentCompositionEntry,
    SegmentRenderAssetPayload,
)
from backend.app.services.edit_asset_store import EditAssetStore


@dataclass(frozen=True)
class PersistedSegmentAssetDescriptor:
    segment_id: str
    segment_asset_id: str
    sample_span_in_block: tuple[int, int]
    alignment_mode: str
    source: str


@dataclass(frozen=True)
class PersistedBlockAssetDescriptor:
    block_id: str
    block_asset_id: str
    sample_rate: int
    audio_sample_count: int
    segment_alignment_mode: str


@dataclass(frozen=True)
class PersistedBlockRenderAssets:
    block_asset: PersistedBlockAssetDescriptor
    segment_assets: list[PersistedSegmentAssetDescriptor]
    timeline_block: BlockCompositionAssetPayload


class BlockRenderAssetPersister:
    def __init__(self, *, asset_store: EditAssetStore) -> None:
        self._asset_store = asset_store

    def persist(
        self,
        *,
        job_id: str,
        request: BlockRenderRequest,
        result: BlockRenderResult,
        block_render_cache_key: str,
        terminal_status: str = "completed",
        base_render_asset_ids: dict[str, str] | None = None,
        base_render_assets: dict[str, SegmentRenderAssetPayload] | None = None,
    ) -> PersistedBlockRenderAssets | None:
        if terminal_status != "completed":
            self._asset_store.cleanup_staging_job(job_id)
            return None

        audio = np.asarray(result.audio, dtype=np.float32)
        segment_ids = [segment.segment_id for segment in request.block.segments]
        if request.block.block_id != result.block_id:
            raise ValueError("Block render result block_id does not match request block_id.")
        if segment_ids != list(result.segment_ids):
            raise ValueError("Block render result segment_ids do not match request block order.")
        if int(audio.size) != result.audio_sample_count:
            raise ValueError("Block render result audio length does not match audio_sample_count.")

        ordered_spans = self._validate_and_order_segment_spans(
            segment_ids=segment_ids,
            spans=result.segment_spans,
            audio_sample_count=result.audio_sample_count,
            alignment_mode=result.segment_alignment_mode,
        )
        output_by_segment_id = {output.segment_id: output for output in result.segment_outputs}
        block_asset_id = self._build_block_asset_id(
            request=request,
            result=result,
            block_render_cache_key=block_render_cache_key,
        )

        try:
            self._write_base_render_assets(
                job_id=job_id,
                base_render_assets=base_render_assets,
                sample_rate=result.sample_rate,
            )
            self._write_block_asset(
                job_id=job_id,
                request=request,
                result=result,
                audio=audio,
                block_asset_id=block_asset_id,
                ordered_spans=ordered_spans,
                output_by_segment_id=output_by_segment_id,
                block_render_cache_key=block_render_cache_key,
                base_render_asset_ids=base_render_asset_ids,
            )
            segment_assets, segment_entries = self._write_derived_segment_assets(
                job_id=job_id,
                request=request,
                result=result,
                audio=audio,
                block_asset_id=block_asset_id,
                ordered_spans=ordered_spans,
                output_by_segment_id=output_by_segment_id,
                base_render_asset_ids=base_render_asset_ids,
            )
            timeline_block = self._build_timeline_block(
                request=request,
                result=result,
                audio=audio,
                block_asset_id=block_asset_id,
                ordered_spans=ordered_spans,
                segment_entries=segment_entries,
            )
            self._asset_store.promote_staging_tree(job_id, "formal")
        except Exception:
            self._asset_store.cleanup_staging_job(job_id)
            raise

        return PersistedBlockRenderAssets(
            block_asset=PersistedBlockAssetDescriptor(
                block_id=result.block_id,
                block_asset_id=block_asset_id,
                sample_rate=result.sample_rate,
                audio_sample_count=result.audio_sample_count,
                segment_alignment_mode=result.segment_alignment_mode,
            ),
            segment_assets=segment_assets,
            timeline_block=timeline_block,
        )

    def _write_base_render_assets(
        self,
        *,
        job_id: str,
        base_render_assets: dict[str, SegmentRenderAssetPayload] | None,
        sample_rate: int,
    ) -> None:
        if not base_render_assets:
            return
        written_asset_ids: set[str] = set()
        for asset in base_render_assets.values():
            if asset.render_asset_id in written_asset_ids:
                continue
            written_asset_ids.add(asset.render_asset_id)
            audio = np.concatenate([asset.left_margin_audio, asset.core_audio, asset.right_margin_audio]).astype(
                np.float32,
                copy=False,
            )
            wav_bytes = build_wav_bytes(
                sample_rate,
                float_audio_chunk_to_pcm16_bytes(audio),
            )
            metadata = {
                "render_asset_id": asset.render_asset_id,
                "segment_id": asset.segment_id,
                "render_version": asset.render_version,
                "semantic_tokens": asset.semantic_tokens,
                "phone_ids": asset.phone_ids,
                "decoder_frame_count": asset.decoder_frame_count,
                "audio_sample_count": asset.audio_sample_count,
                "left_margin_sample_count": asset.left_margin_sample_count,
                "core_sample_count": asset.core_sample_count,
                "right_margin_sample_count": asset.right_margin_sample_count,
                "trace": asset.trace,
            }
            self._asset_store.write_staging_bytes(job_id, f"segments/{asset.render_asset_id}/audio.wav", wav_bytes)
            self._asset_store.write_staging_bytes(
                job_id,
                f"segments/{asset.render_asset_id}/metadata.json",
                json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            )

    def _write_block_asset(
        self,
        *,
        job_id: str,
        request: BlockRenderRequest,
        result: BlockRenderResult,
        audio: np.ndarray,
        block_asset_id: str,
        ordered_spans: list[SegmentSpan],
        output_by_segment_id: dict[str, SegmentOutput],
        block_render_cache_key: str,
        base_render_asset_ids: dict[str, str] | None,
    ) -> None:
        segment_entries = []
        for span in ordered_spans:
            render_asset_id = None
            if result.segment_alignment_mode == "exact":
                render_asset_id = self._build_segment_asset_id(
                    segment_id=span.segment_id,
                    block_asset_id=block_asset_id,
                    sample_span=(span.sample_start, span.sample_end),
                )
            segment_entries.append(
                {
                    "segment_id": span.segment_id,
                    "audio_sample_span": [span.sample_start, span.sample_end],
                    "order_key": self._find_order_key(request=request, segment_id=span.segment_id),
                    "render_asset_id": render_asset_id,
                    "base_render_asset_id": (
                        base_render_asset_ids.get(span.segment_id) if base_render_asset_ids is not None else render_asset_id
                    ),
                    "precision": span.precision,
                    "source": output_by_segment_id.get(span.segment_id).source
                    if output_by_segment_id.get(span.segment_id) is not None
                    else None,
                }
            )
        wav_bytes = build_wav_bytes(
            result.sample_rate,
            float_audio_chunk_to_pcm16_bytes(audio.astype(np.float32, copy=False)),
        )
        edge_entries = self._build_edge_entries(
            request=request,
            ordered_spans=ordered_spans,
            sample_rate=result.sample_rate,
        )
        marker_entries = self._build_marker_entries(
            block_id=result.block_id,
            audio_sample_count=result.audio_sample_count,
            ordered_spans=ordered_spans,
            edge_entries=edge_entries,
        )
        metadata = {
            "block_id": result.block_id,
            "block_asset_id": block_asset_id,
            "segment_ids": list(result.segment_ids),
            "sample_rate": result.sample_rate,
            "audio_sample_count": result.audio_sample_count,
            "adapter_id": request.model_binding.adapter_id,
            "model_instance_id": request.model_binding.model_instance_id,
            "preset_id": request.model_binding.preset_id,
            "model_binding_fingerprint": request.model_binding.binding_fingerprint,
            "segment_alignment_mode": result.segment_alignment_mode,
            "segment_spans": [span.model_dump(mode="json") for span in ordered_spans],
            "segment_entries": segment_entries,
            "segment_output_sources": {
                segment_id: output.source
                for segment_id, output in output_by_segment_id.items()
                if output.source != "unavailable"
            },
            "join_report": result.join_report.model_dump(mode="json") if result.join_report is not None else None,
            "join_report_summary": (
                {
                    "requested_policy": result.join_report.requested_policy,
                    "applied_mode": result.join_report.applied_mode,
                    "enhancement_applied": result.join_report.enhancement_applied,
                }
                if result.join_report is not None
                else None
            ),
            "adapter_trace": result.adapter_trace,
            "diagnostics": result.diagnostics,
            "block_render_cache_key": block_render_cache_key,
            "block_policy_version": request.block_policy_version,
            "edge_entries": [self._serialize_edge_entry(entry) for entry in edge_entries],
            "marker_entries": [self._serialize_marker_entry(entry) for entry in marker_entries],
        }
        self._asset_store.write_staging_bytes(job_id, f"blocks/{block_asset_id}/audio.wav", wav_bytes)
        self._asset_store.write_staging_bytes(
            job_id,
            f"blocks/{block_asset_id}/metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _write_derived_segment_assets(
        self,
        *,
        job_id: str,
        request: BlockRenderRequest,
        result: BlockRenderResult,
        audio: np.ndarray,
        block_asset_id: str,
        ordered_spans: list[SegmentSpan],
        output_by_segment_id: dict[str, SegmentOutput],
        base_render_asset_ids: dict[str, str] | None,
    ) -> tuple[list[PersistedSegmentAssetDescriptor], list[SegmentCompositionEntry]]:
        if result.segment_alignment_mode == "block_only":
            return [], []

        persisted_segment_assets: list[PersistedSegmentAssetDescriptor] = []
        segment_entries: list[SegmentCompositionEntry] = []
        for span in ordered_spans:
            order_key = self._find_order_key(request=request, segment_id=span.segment_id)
            if result.segment_alignment_mode != "exact":
                segment_entries.append(
                    SegmentCompositionEntry(
                        segment_id=span.segment_id,
                        audio_sample_span=(span.sample_start, span.sample_end),
                        order_key=order_key,
                        render_asset_id=None,
                        base_render_asset_id=(
                            base_render_asset_ids.get(span.segment_id) if base_render_asset_ids is not None else None
                        ),
                        precision=span.precision,
                        source=output_by_segment_id.get(span.segment_id).source
                        if output_by_segment_id.get(span.segment_id) is not None
                        else None,
                    )
                )
                continue

            segment_audio = audio[span.sample_start : span.sample_end].astype(np.float32, copy=False)
            if segment_audio.size == 0:
                raise ValueError(f"Exact segment span for '{span.segment_id}' produced empty audio.")
            segment_asset_id = self._build_segment_asset_id(
                segment_id=span.segment_id,
                block_asset_id=block_asset_id,
                sample_span=(span.sample_start, span.sample_end),
            )
            segment_output = output_by_segment_id.get(span.segment_id)
            metadata = {
                "segment_asset_id": segment_asset_id,
                "render_asset_id": segment_asset_id,
                "segment_id": span.segment_id,
                "render_version": 0,
                "parent_block_asset_id": block_asset_id,
                "model_instance_id": request.model_binding.model_instance_id,
                "preset_id": request.model_binding.preset_id,
                "model_binding_fingerprint": request.model_binding.binding_fingerprint,
                "sample_span_in_block": [span.sample_start, span.sample_end],
                "source": segment_output.source if segment_output is not None else "adapter_exact",
                "alignment_mode": result.segment_alignment_mode,
                "audio_sample_count": int(segment_audio.size),
                "left_margin_sample_count": 0,
                "core_sample_count": int(segment_audio.size),
                "right_margin_sample_count": 0,
                "semantic_tokens": [],
                "phone_ids": [],
                "decoder_frame_count": 0,
                "trace": {
                    "derived_from_block": True,
                    "block_asset_id": block_asset_id,
                    "segment_output_source": segment_output.source if segment_output is not None else "adapter_exact",
                },
            }
            wav_bytes = build_wav_bytes(
                result.sample_rate,
                float_audio_chunk_to_pcm16_bytes(segment_audio),
            )
            self._asset_store.write_staging_bytes(job_id, f"segments/{segment_asset_id}/audio.wav", wav_bytes)
            self._asset_store.write_staging_bytes(
                job_id,
                f"segments/{segment_asset_id}/metadata.json",
                json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            persisted_segment_assets.append(
                PersistedSegmentAssetDescriptor(
                    segment_id=span.segment_id,
                    segment_asset_id=segment_asset_id,
                    sample_span_in_block=(span.sample_start, span.sample_end),
                    alignment_mode=result.segment_alignment_mode,
                    source=metadata["source"],
                )
            )
            segment_entries.append(
                SegmentCompositionEntry(
                    segment_id=span.segment_id,
                    audio_sample_span=(span.sample_start, span.sample_end),
                    order_key=order_key,
                    render_asset_id=segment_asset_id,
                    base_render_asset_id=(
                        base_render_asset_ids.get(span.segment_id) if base_render_asset_ids is not None else None
                    ),
                    precision=span.precision,
                    source=metadata["source"],
                )
            )
        return persisted_segment_assets, segment_entries

    def _build_timeline_block(
        self,
        *,
        request: BlockRenderRequest,
        result: BlockRenderResult,
        audio: np.ndarray,
        block_asset_id: str,
        ordered_spans: list[SegmentSpan],
        segment_entries: list[SegmentCompositionEntry],
    ) -> BlockCompositionAssetPayload:
        edge_entries = self._build_edge_entries(
            request=request,
            ordered_spans=ordered_spans,
            sample_rate=result.sample_rate,
        )
        marker_entries = self._build_marker_entries(
            block_id=request.block.block_id,
            audio_sample_count=result.audio_sample_count,
            ordered_spans=ordered_spans,
            edge_entries=edge_entries,
        )
        return BlockCompositionAssetPayload(
            block_id=request.block.block_id,
            block_asset_id=block_asset_id,
            segment_ids=list(result.segment_ids),
            sample_rate=result.sample_rate,
            audio=audio,
            audio_sample_count=result.audio_sample_count,
            segment_entries=segment_entries,
            segment_alignment_mode=result.segment_alignment_mode,
            join_report_summary=(
                {
                    "requested_policy": result.join_report.requested_policy,
                    "applied_mode": result.join_report.applied_mode,
                    "enhancement_applied": result.join_report.enhancement_applied,
                }
                if result.join_report is not None
                else None
            ),
            edge_entries=edge_entries,
            marker_entries=marker_entries,
        )

    def _build_edge_entries(
        self,
        *,
        request: BlockRenderRequest,
        ordered_spans: list[SegmentSpan],
        sample_rate: int,
    ) -> list[EdgeCompositionEntry]:
        if len(ordered_spans) < 2:
            return []
        span_by_segment_id = {span.segment_id: span for span in ordered_spans}
        edge_entries: list[EdgeCompositionEntry] = []
        for edge_control in request.edge_controls:
            left_span = span_by_segment_id.get(edge_control.left_segment_id)
            right_span = span_by_segment_id.get(edge_control.right_segment_id)
            if left_span is None or right_span is None:
                continue
            boundary_start = left_span.sample_end
            pause_end = right_span.sample_start
            pause_sample_count = max(0, int(sample_rate * edge_control.pause_duration_seconds))
            pause_start = max(boundary_start, pause_end - pause_sample_count)
            boundary_end = pause_start
            effective_boundary_strategy = "crossfade_only"
            if boundary_end > boundary_start:
                effective_boundary_strategy = "latent_overlap_then_equal_power_crossfade"
            edge_entries.append(
                EdgeCompositionEntry(
                    edge_id=edge_control.edge_id,
                    left_segment_id=edge_control.left_segment_id,
                    right_segment_id=edge_control.right_segment_id,
                    boundary_strategy="crossfade_only",
                    effective_boundary_strategy=effective_boundary_strategy,
                    pause_duration_seconds=edge_control.pause_duration_seconds,
                    boundary_sample_span=(boundary_start, boundary_end),
                    pause_sample_span=(pause_start, pause_end),
                )
            )
        return edge_entries

    @staticmethod
    def _build_marker_entries(
        *,
        block_id: str,
        audio_sample_count: int,
        ordered_spans: list[SegmentSpan],
        edge_entries: list[EdgeCompositionEntry],
    ) -> list[BlockMarkerEntry]:
        markers = [BlockMarkerEntry(marker_type="block_start", sample=0, related_id=block_id)]
        for span in ordered_spans:
            markers.append(BlockMarkerEntry(marker_type="segment_start", sample=span.sample_start, related_id=span.segment_id))
            markers.append(BlockMarkerEntry(marker_type="segment_end", sample=span.sample_end, related_id=span.segment_id))
        for edge in edge_entries:
            if edge.pause_sample_span[1] > edge.pause_sample_span[0]:
                markers.append(
                    BlockMarkerEntry(
                        marker_type="edge_gap_start",
                        sample=edge.pause_sample_span[0],
                        related_id=edge.edge_id,
                    )
                )
                markers.append(
                    BlockMarkerEntry(
                        marker_type="edge_gap_end",
                        sample=edge.pause_sample_span[1],
                        related_id=edge.edge_id,
                    )
                )
        markers.append(BlockMarkerEntry(marker_type="block_end", sample=audio_sample_count, related_id=block_id))
        return markers

    @staticmethod
    def _serialize_edge_entry(entry: EdgeCompositionEntry) -> dict[str, object]:
        return {
            "edge_id": entry.edge_id,
            "left_segment_id": entry.left_segment_id,
            "right_segment_id": entry.right_segment_id,
            "boundary_strategy": entry.boundary_strategy,
            "effective_boundary_strategy": entry.effective_boundary_strategy,
            "pause_duration_seconds": entry.pause_duration_seconds,
            "boundary_sample_span": list(entry.boundary_sample_span),
            "pause_sample_span": list(entry.pause_sample_span),
        }

    @staticmethod
    def _serialize_marker_entry(entry: BlockMarkerEntry) -> dict[str, object]:
        return {
            "marker_type": entry.marker_type,
            "sample": entry.sample,
            "related_id": entry.related_id,
        }

    def _validate_and_order_segment_spans(
        self,
        *,
        segment_ids: list[str],
        spans: list[SegmentSpan],
        audio_sample_count: int,
        alignment_mode: str,
    ) -> list[SegmentSpan]:
        if alignment_mode == "block_only":
            if spans:
                raise ValueError("block_only result must not provide segment spans.")
            return []

        span_by_segment_id = {span.segment_id: span for span in spans}
        if set(span_by_segment_id) != set(segment_ids):
            raise ValueError("Segment spans must cover every requested segment exactly once.")

        ordered_spans = [span_by_segment_id[segment_id] for segment_id in segment_ids]
        previous_end = 0
        for index, span in enumerate(ordered_spans):
            if span.sample_end <= span.sample_start:
                raise ValueError(f"Segment span for '{span.segment_id}' must have positive length.")
            if span.sample_start < 0 or span.sample_end > audio_sample_count:
                raise ValueError(f"Segment span for '{span.segment_id}' is outside block audio range.")
            if span.sample_start < previous_end:
                raise ValueError(f"Segment span for '{span.segment_id}' overlaps a previous span.")
            if index == 0 and alignment_mode == "exact" and span.sample_start != 0:
                raise ValueError("Exact segment spans must start at sample 0.")
            previous_end = span.sample_end
        if alignment_mode == "exact" and ordered_spans[-1].sample_end != audio_sample_count:
            raise ValueError("Exact segment spans must cover the full block audio.")
        return ordered_spans

    def _build_block_asset_id(
        self,
        *,
        request: BlockRenderRequest,
        result: BlockRenderResult,
        block_render_cache_key: str,
    ) -> str:
        payload = {
            "block_id": result.block_id,
            "cache_key": block_render_cache_key,
            "binding_fingerprint": request.model_binding.binding_fingerprint,
            "model_instance_id": request.model_binding.model_instance_id,
            "preset_id": request.model_binding.preset_id,
            "segment_alignment_mode": result.segment_alignment_mode,
            "sample_rate": result.sample_rate,
            "audio_sample_count": result.audio_sample_count,
            "segment_spans": [span.model_dump(mode="json") for span in result.segment_spans],
            "block_policy_version": request.block_policy_version,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]
        return f"{result.block_id}-{digest}"

    @staticmethod
    def _build_segment_asset_id(
        *,
        segment_id: str,
        block_asset_id: str,
        sample_span: tuple[int, int],
    ) -> str:
        payload = f"{segment_id}|{block_asset_id}|{sample_span[0]}|{sample_span[1]}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
        return f"{segment_id}-{digest}"

    @staticmethod
    def _find_order_key(*, request: BlockRenderRequest, segment_id: str) -> int:
        for segment in request.block.segments:
            if segment.segment_id == segment_id:
                return segment.order_key
        return 0
