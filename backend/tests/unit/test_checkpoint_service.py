import numpy as np

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import BoundaryAssetPayload, build_boundary_asset_id
from backend.app.schemas.edit_session import InitializeEditSessionRequest, RenderProfile
from backend.app.services.render_job_service import RenderPlan
from backend.tests.unit.test_render_job_service import _FakeEditableBackend, _build_service


class _BoundaryContextTrackingBackend(_FakeEditableBackend):
    def __init__(self) -> None:
        super().__init__()
        self.boundary_context_speeds: list[float] = []

    def render_boundary_asset(self, left_asset, right_asset, edge, context) -> BoundaryAssetPayload:
        speed = float(context.inference_config.get("speed", 1.0))
        self.boundary_context_speeds.append(speed)
        sample_count = 2 if speed < 1.0 else 1
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=left_asset.segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=right_asset.segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            ),
            left_segment_id=left_asset.segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=right_asset.segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=edge.boundary_strategy,
            boundary_sample_count=sample_count,
            boundary_audio=np.asarray([0.9] * sample_count, dtype=np.float32),
            trace={"speed": speed},
        )


def test_checkpoint_service_saves_partial_head_and_working_snapshot(tmp_path):
    service = _build_service(tmp_path)
    request = InitializeEditSessionRequest(raw_text="第一句。第二句。", voice_id="demo")
    accepted = service.create_initialize_job(request)
    job = service.get_job(accepted.job.job_id)

    assert job is not None
    plan = RenderPlan(
        job_id=job.job_id,
        job_kind="initialize",
        document_id=job.document_id,
        request=request,
    )
    service._prepare(plan)  # noqa: SLF001

    first_segment = plan.segments[0]
    asset = service._gateway.render_segment_base(first_segment, plan.context)  # noqa: SLF001
    plan.segment_assets[first_segment.segment_id] = asset
    first_segment.render_asset_id = asset.render_asset_id
    first_segment.assembled_audio_span = (0, asset.audio_sample_count)
    first_segment.render_status = "ready"
    first_segment.effective_duration_samples = asset.audio_sample_count
    service._write_segment_asset(plan.job_id, asset)  # noqa: SLF001

    checkpoint, partial_snapshot = service._checkpoint_service.save_partial_head(  # noqa: SLF001
        document_id=plan.document_id,
        job_id=plan.job_id,
        active_session=service._repository.get_active_session(),  # noqa: SLF001
        full_snapshot=service._build_temporary_snapshot(plan),  # noqa: SLF001
        resolve_boundary_context=lambda edge: plan.context,
        segment_assets=plan.segment_assets,
        boundary_assets=plan.boundary_assets,
        status="paused",
    )

    stored_checkpoint = service._repository.get_checkpoint(checkpoint.checkpoint_id)  # noqa: SLF001
    working_snapshot = service._repository.get_snapshot(checkpoint.working_snapshot_id)  # noqa: SLF001
    partial_timeline = service._asset_store.load_timeline_manifest(checkpoint.timeline_manifest_id)  # noqa: SLF001

    assert checkpoint.status == "paused"
    assert checkpoint.resume_token is not None
    assert checkpoint.completed_segment_ids == [first_segment.segment_id]
    assert partial_snapshot.timeline_manifest_id == checkpoint.timeline_manifest_id
    assert stored_checkpoint is not None
    assert working_snapshot is not None
    assert len(partial_snapshot.segments) == 1
    assert len(working_snapshot.segments) == 2
    assert len(partial_timeline.segment_entries) == 1
    assert len(partial_timeline.block_entries) == 1


def test_checkpoint_service_uses_effective_segment_context_when_backfilling_partial_boundaries(tmp_path):
    service = _build_service(tmp_path)
    tracking_backend = _BoundaryContextTrackingBackend()
    gateway = EditableInferenceGateway(tracking_backend)
    service._gateway = gateway  # noqa: SLF001
    service._checkpoint_service._gateway = gateway  # noqa: SLF001

    request = InitializeEditSessionRequest(raw_text="第一句。第二句。第三句。", voice_id="demo")
    accepted = service.create_initialize_job(request)
    job = service.get_job(accepted.job.job_id)

    assert job is not None
    plan = RenderPlan(
        job_id=job.job_id,
        job_kind="initialize",
        document_id=job.document_id,
        request=request,
    )
    service._prepare(plan)  # noqa: SLF001

    slow_profile = RenderProfile(
        render_profile_id="profile-segment-slow",
        scope="segment",
        speed=0.5,
    )
    plan.render_profiles.append(slow_profile)
    plan.segments[0].render_profile_id = slow_profile.render_profile_id

    for segment in plan.segments[:2]:
        snapshot = service._build_temporary_snapshot(plan)  # noqa: SLF001
        context = service._get_segment_context(plan=plan, snapshot=snapshot, segment=segment)  # noqa: SLF001
        asset = service._gateway.render_segment_base(segment, context)  # noqa: SLF001
        plan.segment_assets[segment.segment_id] = asset
        segment.render_asset_id = asset.render_asset_id
        segment.assembled_audio_span = (0, asset.audio_sample_count)
        segment.render_status = "ready"
        segment.effective_duration_samples = asset.audio_sample_count
        service._write_segment_asset(plan.job_id, asset)  # noqa: SLF001

    service._checkpoint_service.save_partial_head(  # noqa: SLF001
        document_id=plan.document_id,
        job_id=plan.job_id,
        active_session=service._repository.get_active_session(),  # noqa: SLF001
        full_snapshot=service._build_temporary_snapshot(plan),  # noqa: SLF001
        resolve_boundary_context=lambda edge: service._get_segment_context(  # noqa: SLF001
            plan=plan,
            snapshot=service._build_temporary_snapshot(plan),  # noqa: SLF001
            segment=next(item for item in plan.segments if item.segment_id == edge.left_segment_id),
        ),
        segment_assets=plan.segment_assets,
        boundary_assets={},
        status="paused",
    )

    assert tracking_backend.boundary_context_speeds == [0.5]
