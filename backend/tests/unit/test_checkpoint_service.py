from backend.app.schemas.edit_session import InitializeEditSessionRequest
from backend.app.services.render_job_service import RenderPlan
from backend.tests.unit.test_render_job_service import _FakeEditableBackend, _build_service


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
    completed_blocks = service._block_planner.build_blocks([first_segment])  # noqa: SLF001
    completed_block_assets = [
        service._composition_builder.compose_block(  # noqa: SLF001
            segments=[asset],
            boundaries=[],
            edges=[],
            block_id=completed_blocks[0].block_id,
        )
    ]

    checkpoint, partial_snapshot = service._checkpoint_service.save_partial_head(  # noqa: SLF001
        document_id=plan.document_id,
        job_id=plan.job_id,
        active_session=service._repository.get_active_session(),  # noqa: SLF001
        full_snapshot=service._build_temporary_snapshot(plan),  # noqa: SLF001
        completed_blocks=completed_blocks,
        remaining_blocks=[],
        completed_block_assets=completed_block_assets,
        status="paused",
    )

    stored_checkpoint = service._repository.get_checkpoint(checkpoint.checkpoint_id)  # noqa: SLF001
    working_snapshot = service._repository.get_snapshot(checkpoint.working_snapshot_id)  # noqa: SLF001
    partial_timeline = service._asset_store.load_timeline_manifest(checkpoint.partial_timeline_manifest_id)  # noqa: SLF001

    assert checkpoint.status == "paused"
    assert checkpoint.resume_token is not None
    assert [block.block_id for block in checkpoint.completed_blocks] == [completed_blocks[0].block_id]
    assert checkpoint.remaining_blocks == []
    assert partial_snapshot.snapshot_id == checkpoint.partial_snapshot_id
    assert partial_snapshot.timeline_manifest_id == checkpoint.partial_timeline_manifest_id
    assert stored_checkpoint is not None
    assert working_snapshot is not None
    assert len(partial_snapshot.segments) == 1
    assert len(working_snapshot.segments) == 2
    assert len(partial_timeline.segment_entries) == 1
    assert len(partial_timeline.block_entries) == 1
    assert partial_timeline.sample_rate == 32000


def test_checkpoint_service_marks_partial_snapshot_as_checkpoint_only_and_preserves_working_snapshot(tmp_path):
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
    completed_blocks = service._block_planner.build_blocks([first_segment])  # noqa: SLF001
    completed_block_assets = [
        service._composition_builder.compose_block(  # noqa: SLF001
            segments=[asset],
            boundaries=[],
            edges=[],
            block_id=completed_blocks[0].block_id,
        )
    ]

    checkpoint, partial_snapshot = service._checkpoint_service.save_partial_head(  # noqa: SLF001
        document_id=plan.document_id,
        job_id=plan.job_id,
        active_session=service._repository.get_active_session(),  # noqa: SLF001
        full_snapshot=service._build_temporary_snapshot(plan),  # noqa: SLF001
        completed_blocks=completed_blocks,
        remaining_blocks=service._block_planner.build_blocks(plan.segments)[1:],  # noqa: SLF001
        completed_block_assets=completed_block_assets,
        status="paused",
    )

    working_snapshot = service._repository.get_snapshot(checkpoint.working_snapshot_id)  # noqa: SLF001

    assert partial_snapshot.snapshot_kind == "checkpoint_partial"
    assert partial_snapshot.document_version == plan.document_version
    assert working_snapshot is not None
    assert working_snapshot.snapshot_kind == "staging"
    assert working_snapshot.document_version == plan.document_version
