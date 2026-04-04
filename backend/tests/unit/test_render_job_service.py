import threading

import numpy as np
import pytest
import torch

from backend.app.schemas.edit_session import AppendSegmentsRequest, CheckpointState
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import EditableEdge, InitializeEditSessionRequest, PreviewRequest, UpdateSegmentRequest
from backend.app.services.block_planner import BlockPlanner
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.render_job_service import RenderJobService


class _FakeVoiceService:
    def get_voice(self, voice_name: str) -> VoiceProfile:
        return VoiceProfile(
            name=voice_name,
            gpt_path="fake.ckpt",
            sovits_path="fake.pth",
            ref_audio="fake.wav",
            ref_text="参考文本",
            ref_lang="zh",
            defaults=VoiceDefaults(),
        )


class _FakeEditableBackend:
    def __init__(
        self,
        *,
        fail_render: bool = False,
        fail_boundary: bool = False,
        gate: threading.Event | None = None,
    ) -> None:
        self.fail_render = fail_render
        self.fail_boundary = fail_boundary
        self.gate = gate

    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext:
        return ReferenceContext(
            reference_context_id="ctx-1",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=resolved_context.reference_audio_path or "fake.wav",
            reference_text=resolved_context.reference_text or "参考文本。",
            reference_language=resolved_context.reference_language or "zh",
            reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
            reference_spectrogram=torch.ones((1, 3, 3), dtype=torch.float32),
            reference_speaker_embedding=torch.ones((1, 4), dtype=torch.float32),
            inference_config_fingerprint="fingerprint",
            inference_config={"margin_frame_count": 0, "speed": resolved_context.speed},
        )

    def render_segment_base(self, segment, context) -> SegmentRenderAssetPayload:
        if self.gate is not None:
            self.gate.wait(timeout=2)
        if self.fail_render:
            raise RuntimeError("segment render failed")
        sample_count = 2 if context.inference_config.get("speed", 1.0) < 1.0 else 1
        base = np.asarray([segment.order_key / 10] * sample_count, dtype=np.float32)
        return SegmentRenderAssetPayload(
            render_asset_id=f"render-{segment.segment_id}",
            segment_id=segment.segment_id,
            render_version=1,
            semantic_tokens=[1, 2],
            phone_ids=[11, 12],
            decoder_frame_count=1,
            audio_sample_count=sample_count,
            left_margin_sample_count=0,
            core_sample_count=sample_count,
            right_margin_sample_count=0,
            left_margin_audio=np.zeros(0, dtype=np.float32),
            core_audio=base,
            right_margin_audio=np.zeros(0, dtype=np.float32),
            trace=None,
        )

    def render_boundary_asset(self, left_asset, right_asset, edge, context) -> BoundaryAssetPayload:
        del edge, context
        if self.fail_boundary:
            raise RuntimeError("boundary render failed")
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=left_asset.segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=right_asset.segment_id,
                right_render_version=right_asset.render_version,
                edge_version=1,
                boundary_strategy="latent_overlap_then_equal_power_crossfade",
            ),
            left_segment_id=left_asset.segment_id,
            left_render_version=1,
            right_segment_id=right_asset.segment_id,
            right_render_version=1,
            edge_version=1,
            boundary_strategy="latent_overlap_then_equal_power_crossfade",
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace=None,
        )


def _build_service(
    tmp_path,
    *,
    fail_render: bool = False,
    fail_boundary: bool = False,
    run_jobs_in_background: bool = False,
    gate=None,
    block_planner: BlockPlanner | None = None,
) -> RenderJobService:
    repository = EditSessionRepository(project_root=tmp_path, db_file=tmp_path / "session.db")
    repository.initialize_schema()
    asset_store = EditAssetStore(
        project_root=tmp_path,
        assets_dir=tmp_path / "assets",
        staging_ttl_seconds=60,
    )
    runtime = EditSessionRuntime()
    session_service = EditSessionService(
        repository=repository,
        asset_store=asset_store,
        runtime=runtime,
        voice_service=_FakeVoiceService(),
    )
    gateway = EditableInferenceGateway(
        _FakeEditableBackend(fail_render=fail_render, fail_boundary=fail_boundary, gate=gate)
    )
    return RenderJobService(
        repository=repository,
        asset_store=asset_store,
        runtime=runtime,
        session_service=session_service,
        gateway=gateway,
        block_planner=block_planner,
        run_jobs_in_background=run_jobs_in_background,
    )


def test_run_transaction_executes_prepare_render_compose_commit_in_order(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    steps: list[str] = []
    plan = object()

    monkeypatch.setattr(service, "_prepare", lambda value: steps.append(f"prepare:{id(value)}"))
    monkeypatch.setattr(service, "_render", lambda value: steps.append(f"render:{id(value)}"))
    monkeypatch.setattr(service, "_compose", lambda value: steps.append(f"compose:{id(value)}"))
    monkeypatch.setattr(service, "_commit", lambda value: steps.append(f"commit:{id(value)}"))

    service._run_transaction(plan)

    assert steps == [f"prepare:{id(plan)}", f"render:{id(plan)}", f"compose:{id(plan)}", f"commit:{id(plan)}"]


def test_run_initialize_job_commits_ready_session_and_snapshots(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()

    assert snapshot.session_status == "ready"
    assert snapshot.document_version == 1
    assert snapshot.total_segment_count == 2
    assert snapshot.total_edge_count == 1
    assert snapshot.ready_block_count == 1
    assert snapshot.composition_manifest_id is not None


def test_run_initialize_job_supports_zh_period_segment_boundary_mode(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text=(
                "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。"
                "他放下话筒，摸着胡须，琢磨起来。"
                "不，他太愚蠢了。"
                "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。"
                "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。"
            ),
            voice_id="demo",
            text_language="zh",
            segment_boundary_mode="zh_period",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()

    assert snapshot.session_status == "ready"
    assert [segment.raw_text for segment in snapshot.segments] == [
        "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。",
        "他放下话筒，摸着胡须，琢磨起来。",
        "不，他太愚蠢了。",
        "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。",
        "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。",
    ]
    assert snapshot.total_segment_count == 5
    assert snapshot.total_edge_count == 4


def test_run_initialize_job_marks_job_failed_when_render_raises(tmp_path):
    service = _build_service(tmp_path, fail_render=True)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()
    job = service.get_job(accepted.job.job_id)

    assert snapshot.session_status == "failed"
    assert job is not None
    assert job.status == "failed"
    assert "segment render failed" in job.message


def test_run_initialize_job_rolls_back_staging_when_boundary_render_fails(tmp_path):
    service = _build_service(tmp_path, fail_boundary=True)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)

    assert not (tmp_path / "assets" / "staging" / accepted.job.job_id).exists()
    assert any((tmp_path / "assets" / "formal" / "segments").rglob("audio.wav"))
    assert not any((tmp_path / "assets" / "formal" / "boundaries").rglob("audio.wav"))
    assert not any((tmp_path / "assets" / "formal" / "compositions").rglob("*.wav"))


def test_build_fallback_boundary_asset_crossfades_segment_margins_without_model_rerender(tmp_path):
    service = _build_service(tmp_path)
    left_asset = SegmentRenderAssetPayload(
        render_asset_id="render-left",
        segment_id="seg-left",
        render_version=3,
        semantic_tokens=[1],
        phone_ids=[11],
        decoder_frame_count=2,
        audio_sample_count=4,
        left_margin_sample_count=0,
        core_sample_count=2,
        right_margin_sample_count=2,
        left_margin_audio=np.zeros(0, dtype=np.float32),
        core_audio=np.asarray([0.2, 0.3], dtype=np.float32),
        right_margin_audio=np.asarray([1.0, 1.0], dtype=np.float32),
        trace=None,
    )
    right_asset = SegmentRenderAssetPayload(
        render_asset_id="render-right",
        segment_id="seg-right",
        render_version=5,
        semantic_tokens=[2],
        phone_ids=[12],
        decoder_frame_count=2,
        audio_sample_count=4,
        left_margin_sample_count=2,
        core_sample_count=2,
        right_margin_sample_count=0,
        left_margin_audio=np.asarray([0.0, 0.0], dtype=np.float32),
        core_audio=np.asarray([0.4, 0.5], dtype=np.float32),
        right_margin_audio=np.zeros(0, dtype=np.float32),
        trace=None,
    )
    edge = EditableEdge(
        edge_id="edge-seg-left-seg-right",
        document_id="doc-1",
        left_segment_id="seg-left",
        right_segment_id="seg-right",
        edge_version=2,
    )

    boundary = service._build_fallback_boundary_asset(left_asset, right_asset, edge)

    assert boundary.left_render_version == 3
    assert boundary.right_render_version == 5
    assert boundary.boundary_sample_count == 2
    assert boundary.trace == {"boundary_kind": "fallback_equal_power_crossfade"}
    assert np.allclose(boundary.boundary_audio, np.asarray([1.0, 0.0], dtype=np.float32), atol=1e-6)


def test_edit_job_only_recomposes_target_blocks(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        block_planner=BlockPlanner(
            sample_rate=1,
            min_block_seconds=100,
            max_block_seconds=1000,
            max_segment_count=2,
        ),
    )
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    initial_snapshot = service.get_head_snapshot()
    target_segment_id = initial_snapshot.segments[0].segment_id
    untouched_block_id = initial_snapshot.block_ids[1]
    composed_block_ids: list[str] = []
    original_compose_block = service._composition_builder.compose_block

    def _record_compose_block(*args, **kwargs):
        composed_block_ids.append(kwargs["block_id"])
        return original_compose_block(*args, **kwargs)

    monkeypatch.setattr(service._composition_builder, "compose_block", _record_compose_block)

    edit_job = service.create_update_segment_job(
        target_segment_id,
        UpdateSegmentRequest(raw_text="第一句已修改。"),
    )
    service.run_edit_job(edit_job.job.job_id)

    assert len(composed_block_ids) == 1
    assert untouched_block_id not in composed_block_ids


def test_create_update_segment_job_preserves_planner_metadata_for_queued_edit_job(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()

    edit_job = service.create_update_segment_job(
        snapshot.segments[0].segment_id,
        UpdateSegmentRequest(raw_text="第一句已修改。"),
    )
    queued_job = service._queued_edit_jobs[edit_job.job.job_id]  # noqa: SLF001

    assert queued_job.earliest_changed_order_key == 1
    assert queued_job.timeline_reflow_required is True
    assert queued_job.change_reason == "segment_update"


def test_run_edit_job_restores_planner_metadata_into_render_plan(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()
    captured: dict[str, object] = {}

    def _capture_plan(plan):
        captured["earliest_changed_order_key"] = plan.earliest_changed_order_key
        captured["timeline_reflow_required"] = plan.timeline_reflow_required
        captured["change_reason"] = plan.change_reason

    monkeypatch.setattr(service, "_run_transaction", _capture_plan)

    edit_job = service.create_update_segment_job(
        snapshot.segments[0].segment_id,
        UpdateSegmentRequest(raw_text="第一句已修改。"),
    )
    service.run_edit_job(edit_job.job.job_id)

    assert captured == {
        "earliest_changed_order_key": 1,
        "timeline_reflow_required": True,
        "change_reason": "segment_update",
    }


def test_build_preview_selects_segment_edge_and_block_after_commit(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()
    segment_id = snapshot.segments[0].segment_id
    edge_id = snapshot.edges[0].edge_id
    block_id = service.get_head_snapshot().block_ids[0]

    segment_preview = service.build_preview(PreviewRequest(segment_id=segment_id))
    edge_preview = service.build_preview(PreviewRequest(edge_id=edge_id))
    block_preview = service.build_preview(PreviewRequest(block_id=block_id))

    assert segment_preview.preview_kind == "segment"
    assert edge_preview.preview_kind == "edge"
    assert block_preview.preview_kind == "block"
    assert segment_preview.audio.size > 0
    assert edge_preview.audio.size > 0
    assert block_preview.audio.size > 0


def test_cancel_job_requests_runtime_cancel(tmp_path):
    gate = threading.Event()
    service = _build_service(tmp_path, run_jobs_in_background=False, gate=gate)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )

    cancelled = service.cancel_job(accepted.job.job_id)
    job = service.get_job(accepted.job.job_id)

    assert cancelled is True
    assert job is not None
    assert job.cancel_requested is True
    assert job.status == "cancel_requested"


def test_initialize_job_cancel_during_compose_becomes_cancelled_partial(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    original_compose = service._compose  # noqa: SLF001

    def _cancel_then_compose(plan):
        cancelled = service.cancel_job(plan.job_id)
        assert cancelled is True
        return original_compose(plan)

    monkeypatch.setattr(service, "_compose", _cancel_then_compose)

    service.run_initialize_job(accepted.job.job_id)

    job = service.get_job(accepted.job.job_id)
    checkpoint = service._checkpoint_service.get_current_checkpoint(accepted.job.document_id)  # noqa: SLF001

    assert job is not None
    assert job.status == "cancelled_partial"
    assert checkpoint is not None
    assert checkpoint.status == "cancelled_partial"


def test_create_resume_job_accepts_resumable_checkpoint(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()

    edit_job = service.create_append_job(
        AppendSegmentsRequest(
            raw_text="第四句。第五句。",
            text_language="auto",
        )
    )
    service.pause_job(edit_job.job.job_id)
    service.run_edit_job(edit_job.job.job_id)

    checkpoint = service._checkpoint_service.get_current_checkpoint(snapshot.document_id)  # noqa: SLF001
    assert checkpoint is not None
    service._repository.save_checkpoint(  # noqa: SLF001
        CheckpointState(
            checkpoint_id=checkpoint.checkpoint_id,
            document_id=checkpoint.document_id,
            job_id=checkpoint.job_id,
            document_version=checkpoint.document_version,
            head_snapshot_id=checkpoint.head_snapshot_id,
            timeline_manifest_id=checkpoint.timeline_manifest_id,
            working_snapshot_id=checkpoint.working_snapshot_id,
            next_segment_cursor=checkpoint.next_segment_cursor,
            completed_segment_ids=list(checkpoint.completed_segment_ids),
            remaining_segment_ids=list(checkpoint.remaining_segment_ids),
            status="resumable",
            resume_token=checkpoint.resume_token,
            updated_at=checkpoint.updated_at,
        )
    )

    resumed = service.create_resume_job(edit_job.job.job_id)

    assert resumed.job.job_id != edit_job.job.job_id
    assert service._queued_edit_jobs[resumed.job.job_id].job_kind == "resume"  # noqa: SLF001
