from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableSegment,
    UpdateSegmentRequest,
)
from backend.app.services.edge_service import EdgeService
from backend.app.text.segment_standardizer import (
    LONG_EDIT_COST_RISK,
    SHORT_NATURALNESS_RISK,
    build_segment_display_text,
    extract_segment_stem,
    standardize_segment_text,
    standardize_segment_text_state,
    standardize_segment_texts,
)
from backend.app.text.terminal_capsule import SegmentTextState


@dataclass(frozen=True)
class SegmentMutationResult:
    snapshot: DocumentSnapshot
    segment: EditableSegment | None


@dataclass(frozen=True)
class SegmentBatchMutationResult:
    snapshot: DocumentSnapshot
    segments: list[EditableSegment]


class SegmentService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        edge_service: EdgeService,
    ) -> None:
        self._repository = repository
        self._edge_service = edge_service

    def list_segments(
        self,
        *,
        limit: int,
        cursor: int | None,
        snapshot: DocumentSnapshot | None = None,
    ) -> list[EditableSegment]:
        head_snapshot = snapshot or self._get_head_snapshot()
        return self._repository.list_segments(
            head_snapshot.document_id,
            limit=limit,
            cursor=cursor,
            snapshot_id=head_snapshot.snapshot_id,
        )

    def insert_segment(
        self,
        *,
        after_segment_id: str | None,
        raw_text: str,
        text_language: str,
        inference_override: dict[str, object],
        group_id: str | None = None,
        render_profile_id: str | None = None,
        voice_binding_id: str | None = None,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        insert_index = 0
        if after_segment_id is not None:
            insert_index = next((index + 1 for index, item in enumerate(segments) if item.segment_id == after_segment_id), -1)
            if insert_index < 0:
                raise EditSessionNotFoundError(f"Segment '{after_segment_id}' not found.")

        standardized = standardize_segment_text(raw_text, text_language)
        inserted_segment = self._build_editable_segment(
            document_id=head_snapshot.document_id,
            text_language=text_language,
            standardized=standardized,
            group_id=group_id,
            render_profile_id=render_profile_id,
            voice_binding_id=voice_binding_id,
            inference_override=dict(inference_override),
        )
        segments.insert(insert_index, inserted_segment)
        normalized_segments = self._normalize_segment_order(segments)
        inserted_segment = next(item for item in normalized_segments if item.segment_id == inserted_segment.segment_id)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=inserted_segment,
        )

    def append_segments(
        self,
        *,
        after_segment_id: str | None,
        raw_segments: list[str],
        text_language: str,
        group_id: str | None = None,
        render_profile_id: str | None = None,
        voice_binding_id: str | None = None,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentBatchMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        insert_index = len(segments)
        if after_segment_id is not None:
            insert_index = next((index + 1 for index, item in enumerate(segments) if item.segment_id == after_segment_id), -1)
            if insert_index < 0:
                raise EditSessionNotFoundError(f"Segment '{after_segment_id}' not found.")

        inserted_segments: list[EditableSegment] = []
        standardized_batch = standardize_segment_texts(raw_segments, text_language)
        for standardized in standardized_batch.segments:
            inserted_segments.append(
                self._build_editable_segment(
                    document_id=head_snapshot.document_id,
                    text_language=text_language,
                    standardized=standardized,
                    group_id=group_id,
                    render_profile_id=render_profile_id,
                    voice_binding_id=voice_binding_id,
                    inference_override={},
                )
            )
        segments[insert_index:insert_index] = inserted_segments
        normalized_segments = self._normalize_segment_order(segments)
        inserted_ids = {segment.segment_id for segment in inserted_segments}
        normalized_inserted_segments = [segment for segment in normalized_segments if segment.segment_id in inserted_ids]
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentBatchMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segments=normalized_inserted_segments,
        )

    def update_segment(
        self,
        segment_id: str,
        patch: UpdateSegmentRequest,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        target_index = next((index for index, item in enumerate(segments) if item.segment_id == segment_id), None)
        if target_index is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")

        current_segment = segments[target_index]
        updated_segment = current_segment.model_copy(deep=True)
        rerender_required = False

        if patch.text_patch is not None or patch.text_language is not None:
            next_text_language = patch.text_language or current_segment.text_language
            text_patch = patch.text_patch
            standardized = standardize_segment_text_state(
                SegmentTextState(
                    stem=text_patch.stem if text_patch and text_patch.stem is not None else current_segment.stem,
                    terminal_raw=(
                        text_patch.terminal_raw
                        if text_patch and text_patch.terminal_raw is not None
                        else current_segment.terminal_raw
                    ),
                    terminal_closer_suffix=(
                        text_patch.terminal_closer_suffix
                        if text_patch and text_patch.terminal_closer_suffix is not None
                        else current_segment.terminal_closer_suffix
                    ),
                    terminal_source=(
                        text_patch.terminal_source
                        if text_patch and text_patch.terminal_source is not None
                        else current_segment.terminal_source
                    ),
                ),
                next_text_language,
            )
            text_changed = any(
                (
                    standardized.stem != current_segment.stem,
                    standardized.terminal_raw != current_segment.terminal_raw,
                    standardized.terminal_closer_suffix != current_segment.terminal_closer_suffix,
                    standardized.terminal_source != current_segment.terminal_source,
                    next_text_language != current_segment.text_language,
                    standardized.detected_language != current_segment.detected_language,
                    standardized.inference_exclusion_reason != current_segment.inference_exclusion_reason,
                    standardized.risk_flags != current_segment.risk_flags,
                )
            )
            if text_changed:
                updated_segment.stem = standardized.stem
                updated_segment.text_language = next_text_language
                updated_segment.terminal_raw = standardized.terminal_raw
                updated_segment.terminal_closer_suffix = standardized.terminal_closer_suffix
                updated_segment.terminal_source = standardized.terminal_source
                updated_segment.detected_language = standardized.detected_language
                updated_segment.inference_exclusion_reason = standardized.inference_exclusion_reason
                updated_segment.risk_flags = standardized.risk_flags
                rerender_required = True
        if patch.inference_override is not None and patch.inference_override != current_segment.inference_override:
            updated_segment.inference_override = dict(patch.inference_override)
            rerender_required = True
        if rerender_required:
            updated_segment.render_version = current_segment.render_version + 1
            updated_segment.render_asset_id = None
            updated_segment.base_render_asset_id = None
            updated_segment.assembled_audio_span = None

        segments[target_index] = updated_segment
        normalized_segments = self._normalize_segment_order(segments)
        updated_segment = next(item for item in normalized_segments if item.segment_id == segment_id)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=updated_segment,
        )

    def update_segment_render_profile(
        self,
        segment_id: str,
        render_profile_id: str | None,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        return self._update_segment_binding_fields(
            segment_id,
            snapshot=snapshot,
            render_profile_id=render_profile_id,
            voice_binding_id=None,
            update_voice_binding=False,
        )

    def update_segment_voice_binding(
        self,
        segment_id: str,
        voice_binding_id: str | None,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        return self._update_segment_binding_fields(
            segment_id,
            snapshot=snapshot,
            render_profile_id=None,
            voice_binding_id=voice_binding_id,
            update_voice_binding=True,
        )

    def delete_segment(
        self,
        segment_id: str,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments if item.segment_id != segment_id]
        if len(segments) == len(head_snapshot.segments):
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")

        normalized_segments = self._normalize_segment_order(segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=None,
        )

    def swap_segments(
        self,
        first_segment_id: str,
        second_segment_id: str,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        if first_segment_id == second_segment_id:
            raise ValueError("Swap segment ids must be different.")

        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        first_index = next((index for index, item in enumerate(segments) if item.segment_id == first_segment_id), None)
        second_index = next((index for index, item in enumerate(segments) if item.segment_id == second_segment_id), None)
        if first_index is None:
            raise EditSessionNotFoundError(f"Segment '{first_segment_id}' not found.")
        if second_index is None:
            raise EditSessionNotFoundError(f"Segment '{second_segment_id}' not found.")

        segments[first_index], segments[second_index] = segments[second_index], segments[first_index]
        normalized_segments = self._normalize_segment_order(segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
            default_boundary_strategy="crossfade_only",
            lock_new_boundary_strategy=True,
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=None,
        )

    def move_range(
        self,
        segment_ids: list[str],
        *,
        after_segment_id: str | None,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        if not segment_ids:
            raise ValueError("Move range requires at least one segment.")
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        index_by_id = {segment.segment_id: index for index, segment in enumerate(segments)}
        try:
            moving_indexes = [index_by_id[segment_id] for segment_id in segment_ids]
        except KeyError as exc:
            raise EditSessionNotFoundError(f"Segment '{exc.args[0]}' not found.") from exc
        sorted_indexes = sorted(moving_indexes)
        expected_indexes = list(range(sorted_indexes[0], sorted_indexes[0] + len(sorted_indexes)))
        if sorted_indexes != expected_indexes:
            raise ValueError("Move range segments must be contiguous in current order.")
        if after_segment_id is not None and after_segment_id not in index_by_id:
            raise EditSessionNotFoundError(f"Segment '{after_segment_id}' not found.")
        moving_set = set(segment_ids)
        moving_segments = [segment for segment in segments if segment.segment_id in moving_set]
        remaining_segments = [segment for segment in segments if segment.segment_id not in moving_set]
        insert_index = len(remaining_segments)
        if after_segment_id is not None:
            insert_index = next(
                (index + 1 for index, segment in enumerate(remaining_segments) if segment.segment_id == after_segment_id),
                -1,
            )
            if insert_index < 0:
                raise ValueError("Move target cannot be inside the moving range.")
        remaining_segments[insert_index:insert_index] = moving_segments
        normalized_segments = self._normalize_segment_order(remaining_segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
            default_boundary_strategy="crossfade_only",
            lock_new_boundary_strategy=True,
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=None,
        )

    def reorder_segments(
        self,
        ordered_segment_ids: list[str],
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        if not ordered_segment_ids:
            raise ValueError("Reorder requires at least one segment.")
        if len(set(ordered_segment_ids)) != len(ordered_segment_ids):
            raise ValueError("Reorder segment ids must be unique.")

        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        segment_by_id = {segment.segment_id: segment for segment in segments}
        if len(ordered_segment_ids) != len(segments) or set(ordered_segment_ids) != set(segment_by_id):
            raise ValueError("Reorder segment ids must match current snapshot exactly.")

        reordered_segments = [segment_by_id[segment_id] for segment_id in ordered_segment_ids]
        normalized_segments = self._normalize_segment_order(reordered_segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
            default_boundary_strategy="crossfade_only",
            lock_new_boundary_strategy=True,
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=None,
        )

    def split_segment(
        self,
        segment_id: str,
        *,
        left_text: str,
        right_text: str,
        text_language: str | None = None,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentBatchMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        target_index = next((index for index, item in enumerate(segments) if item.segment_id == segment_id), None)
        if target_index is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")
        original = segments[target_index]
        next_language = text_language or original.text_language
        standardized_batch = standardize_segment_texts([left_text, right_text], next_language)
        left_standardized, right_standardized = standardized_batch.segments
        left_segment = self._build_editable_segment(
            document_id=original.document_id,
            text_language=next_language,
            standardized=left_standardized,
            group_id=original.group_id,
            render_profile_id=original.render_profile_id,
            voice_binding_id=original.voice_binding_id,
            inference_override=dict(original.inference_override),
        )
        right_segment = self._build_editable_segment(
            document_id=original.document_id,
            text_language=next_language,
            standardized=right_standardized,
            group_id=original.group_id,
            render_profile_id=original.render_profile_id,
            voice_binding_id=original.voice_binding_id,
            inference_override=dict(original.inference_override),
        )
        segments[target_index:target_index + 1] = [left_segment, right_segment]
        normalized_segments = self._normalize_segment_order(segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentBatchMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segments=[
                next(item for item in normalized_segments if item.segment_id == left_segment.segment_id),
                next(item for item in normalized_segments if item.segment_id == right_segment.segment_id),
            ],
        )

    def merge_segments(
        self,
        left_segment_id: str,
        right_segment_id: str,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        left_index = next((index for index, item in enumerate(segments) if item.segment_id == left_segment_id), None)
        right_index = next((index for index, item in enumerate(segments) if item.segment_id == right_segment_id), None)
        if left_index is None:
            raise EditSessionNotFoundError(f"Segment '{left_segment_id}' not found.")
        if right_index is None:
            raise EditSessionNotFoundError(f"Segment '{right_segment_id}' not found.")
        if right_index != left_index + 1:
            raise ValueError("Merge requires adjacent segments in current order.")
        left_segment = segments[left_index]
        right_segment = segments[right_index]
        left_stem = extract_segment_stem(
            stem=left_segment.stem,
            terminal_raw=left_segment.terminal_raw,
            terminal_closer_suffix=left_segment.terminal_closer_suffix,
            terminal_source=left_segment.terminal_source,
        )
        right_display_text = build_segment_display_text(
            stem=right_segment.stem,
            text_language=right_segment.text_language,
            terminal_raw=right_segment.terminal_raw,
            terminal_closer_suffix=right_segment.terminal_closer_suffix,
            terminal_source=right_segment.terminal_source,
        )
        merged_standardized = standardize_segment_text(f"{left_stem}{right_display_text}", left_segment.text_language)
        merged_segment = self._build_editable_segment(
            document_id=left_segment.document_id,
            text_language=left_segment.text_language,
            standardized=merged_standardized,
            group_id=left_segment.group_id,
            render_profile_id=left_segment.render_profile_id,
            voice_binding_id=left_segment.voice_binding_id,
            inference_override=dict(left_segment.inference_override),
        )
        segments[left_index:right_index + 1] = [merged_segment]
        normalized_segments = self._normalize_segment_order(segments)
        edges = self._edge_service.rebuild_neighbor_edges(
            normalized_segments,
            existing_edges=head_snapshot.edges,
            default_pause_duration_seconds=self._default_pause_duration_seconds(),
        )
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(head_snapshot, segments=normalized_segments, edges=edges),
            segment=next(item for item in normalized_segments if item.segment_id == merged_segment.segment_id),
        )

    def update_segments_render_profile(
        self,
        segment_ids: list[str],
        render_profile_id: str | None,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentBatchMutationResult:
        return self._update_segment_binding_fields_batch(
            segment_ids,
            snapshot=snapshot,
            render_profile_id=render_profile_id,
            voice_binding_id=None,
            update_voice_binding=False,
        )

    def update_segments_voice_binding(
        self,
        segment_ids: list[str],
        voice_binding_id: str | None,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentBatchMutationResult:
        return self._update_segment_binding_fields_batch(
            segment_ids,
            snapshot=snapshot,
            render_profile_id=None,
            voice_binding_id=voice_binding_id,
            update_voice_binding=True,
        )

    def _get_head_snapshot(self) -> DocumentSnapshot:
        active_session = self._repository.get_active_session()
        if active_session is None or active_session.head_snapshot_id is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        snapshot = self._repository.get_snapshot(active_session.head_snapshot_id)
        if snapshot is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        return snapshot

    def _default_pause_duration_seconds(self) -> float:
        active_session = self._repository.get_active_session()
        if active_session is None or active_session.initialize_request is None:
            return 0.3
        return active_session.initialize_request.pause_duration_seconds

    def _update_segment_binding_fields(
        self,
        segment_id: str,
        *,
        snapshot: DocumentSnapshot | None,
        render_profile_id: str | None,
        voice_binding_id: str | None,
        update_voice_binding: bool,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        target_index = next((index for index, item in enumerate(segments) if item.segment_id == segment_id), None)
        if target_index is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")

        updated_segment = segments[target_index].model_copy(deep=True)
        if update_voice_binding:
            updated_segment.voice_binding_id = voice_binding_id
        else:
            updated_segment.render_profile_id = render_profile_id
        segments[target_index] = updated_segment
        normalized_segments = self._normalize_segment_order(segments)
        return SegmentMutationResult(
            snapshot=self._clone_snapshot(
                head_snapshot,
                segments=normalized_segments,
                edges=[edge.model_copy(deep=True) for edge in head_snapshot.edges],
            ),
            segment=next(item for item in normalized_segments if item.segment_id == segment_id),
        )

    def _update_segment_binding_fields_batch(
        self,
        segment_ids: list[str],
        *,
        snapshot: DocumentSnapshot | None,
        render_profile_id: str | None,
        voice_binding_id: str | None,
        update_voice_binding: bool,
    ) -> SegmentBatchMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        target_ids = set(segment_ids)
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        existing_ids = {segment.segment_id for segment in segments}
        missing_ids = [segment_id for segment_id in segment_ids if segment_id not in existing_ids]
        if missing_ids:
            raise EditSessionNotFoundError(f"Segment '{missing_ids[0]}' not found.")
        updated_ids: list[str] = []
        for index, segment in enumerate(segments):
            if segment.segment_id not in target_ids:
                continue
            updated_segment = segment.model_copy(deep=True)
            if update_voice_binding:
                updated_segment.voice_binding_id = voice_binding_id
            else:
                updated_segment.render_profile_id = render_profile_id
            segments[index] = updated_segment
            updated_ids.append(updated_segment.segment_id)
        normalized_segments = self._normalize_segment_order(segments)
        return SegmentBatchMutationResult(
            snapshot=self._clone_snapshot(
                head_snapshot,
                segments=normalized_segments,
                edges=[edge.model_copy(deep=True) for edge in head_snapshot.edges],
            ),
            segments=[segment for segment in normalized_segments if segment.segment_id in set(updated_ids)],
        )

    @staticmethod
    def _normalize_segment_order(segments: list[EditableSegment]) -> list[EditableSegment]:
        normalized: list[EditableSegment] = []
        for index, segment in enumerate(segments, start=1):
            previous_segment_id = normalized[-1].segment_id if normalized else None
            next_segment_id = segments[index].segment_id if index < len(segments) else None
            normalized.append(
                segment.model_copy(
                    update={
                        "order_key": index,
                        "previous_segment_id": previous_segment_id,
                        "next_segment_id": next_segment_id,
                    }
                )
            )
        return normalized

    @staticmethod
    def _build_editable_segment(
        *,
        document_id: str,
        text_language: str,
        standardized,
        group_id: str | None = None,
        render_profile_id: str | None = None,
        voice_binding_id: str | None = None,
        inference_override: dict[str, object] | None = None,
    ) -> EditableSegment:
        return EditableSegment(
            segment_id=f"segment-{uuid4().hex}",
            document_id=document_id,
            order_key=0,
            stem=standardized.stem,
            text_language=text_language,
            terminal_raw=standardized.terminal_raw,
            terminal_closer_suffix=standardized.terminal_closer_suffix,
            terminal_source=standardized.terminal_source,
            detected_language=standardized.detected_language,
            inference_exclusion_reason=standardized.inference_exclusion_reason,
            render_version=1,
            render_asset_id=None,
            base_render_asset_id=None,
            group_id=group_id,
            render_profile_id=render_profile_id,
            voice_binding_id=voice_binding_id,
            inference_override=dict(inference_override or {}),
            risk_flags=standardized.risk_flags,
            assembled_audio_span=None,
            render_status="pending",
        )

    @staticmethod
    def _clone_snapshot(
        base_snapshot: DocumentSnapshot,
        *,
        segments: list[EditableSegment],
        edges: list,
    ) -> DocumentSnapshot:
        return base_snapshot.model_copy(
            deep=True,
            update={
                "document_version": base_snapshot.document_version + 1,
                "segments": segments,
                "edges": edges,
                "block_ids": [],
                "composition_manifest_id": None,
                "playback_map_version": None,
            },
        )

    @staticmethod
    def describe_segment_text(raw_text: str) -> tuple[str, list[str]]:
        standardized = standardize_segment_text(raw_text, "unknown")
        return standardized.raw_text, standardized.risk_flags
