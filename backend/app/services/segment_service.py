from __future__ import annotations

from dataclasses import dataclass
import string
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.inference.text_processing import normalize_whitespace
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    CreateSegmentRequest,
    DocumentSnapshot,
    EditableSegment,
    UpdateSegmentRequest,
)
from backend.app.services.edge_service import EdgeService


SHORT_NATURALNESS_RISK = "short_naturalness_risk"
LONG_EDIT_COST_RISK = "long_edit_cost_risk"
_STRONG_BOUNDARY_TERMINATORS = ("。", "！", "？", "!", "?", "…")
_NON_SPEECH_CHARACTERS = set(string.punctuation) | set("，。！？；：、（）【】《》“”‘’…·—")
_APPROX_CHARS_PER_SECOND = 5.0
_SHORT_SEGMENT_SECONDS = 3.0
_LONG_SEGMENT_SECONDS = 30.0


@dataclass(frozen=True)
class SegmentMutationResult:
    snapshot: DocumentSnapshot
    segment: EditableSegment | None


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
        snapshot: DocumentSnapshot | None = None,
    ) -> SegmentMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        segments = [item.model_copy(deep=True) for item in head_snapshot.segments]
        insert_index = 0
        if after_segment_id is not None:
            insert_index = next((index + 1 for index, item in enumerate(segments) if item.segment_id == after_segment_id), -1)
            if insert_index < 0:
                raise EditSessionNotFoundError(f"Segment '{after_segment_id}' not found.")

        normalized_text, risk_flags = self.describe_segment_text(raw_text)
        inserted_segment = EditableSegment(
            segment_id=f"segment-{uuid4().hex}",
            document_id=head_snapshot.document_id,
            order_key=0,
            raw_text=normalized_text,
            normalized_text=normalized_text,
            text_language=text_language,
            render_version=1,
            render_asset_id=None,
            inference_override=dict(inference_override),
            risk_flags=risk_flags,
            assembled_audio_span=None,
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

        if patch.raw_text is not None:
            normalized_text, risk_flags = self.describe_segment_text(patch.raw_text)
            if normalized_text != current_segment.raw_text:
                updated_segment.raw_text = normalized_text
                updated_segment.normalized_text = normalize_whitespace(normalized_text)
                updated_segment.risk_flags = risk_flags
                rerender_required = True
        if patch.text_language is not None and patch.text_language != current_segment.text_language:
            updated_segment.text_language = patch.text_language
            rerender_required = True
        if patch.inference_override is not None and patch.inference_override != current_segment.inference_override:
            updated_segment.inference_override = dict(patch.inference_override)
            rerender_required = True
        if rerender_required:
            updated_segment.render_version = current_segment.render_version + 1
            updated_segment.render_asset_id = None
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
                "raw_text": "".join(segment.raw_text for segment in segments),
                "normalized_text": "".join(segment.normalized_text for segment in segments),
                "segments": segments,
                "edges": edges,
                "block_ids": [],
                "composition_manifest_id": None,
                "playback_map_version": None,
            },
        )

    @staticmethod
    def describe_segment_text(raw_text: str) -> tuple[str, list[str]]:
        normalized = normalize_whitespace(raw_text)
        if not normalized:
            raise ValueError("Segment text must not be empty.")
        if not normalized.endswith(_STRONG_BOUNDARY_TERMINATORS):
            raise ValueError("Segment text must end with a strong boundary punctuation (强标点).")

        speech_char_count = sum(
            1
            for char in normalized
            if not char.isspace() and char not in _NON_SPEECH_CHARACTERS
        )
        if speech_char_count <= 0:
            raise ValueError("Segment text must contain readable speech content.")

        approx_seconds = speech_char_count / _APPROX_CHARS_PER_SECOND
        risk_flags: list[str] = []
        # v0.0.1 先用字符数近似语速，兑现设计文档里的长短段风险提示。
        if approx_seconds < _SHORT_SEGMENT_SECONDS:
            risk_flags.append(SHORT_NATURALNESS_RISK)
        if approx_seconds > _LONG_SEGMENT_SECONDS:
            risk_flags.append(LONG_EDIT_COST_RISK)
        return normalized, risk_flags
