import threading
import shutil
import time
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from backend.app.inference.adapter_definition import AdapterBlockLimits, AdapterDefinition
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import (
    AdapterCapabilities,
    BlockRenderResult,
    BlockScopeUnsupported,
    BoundaryResult,
    JoinReport,
    SegmentOutput,
    SegmentScopeUnsupported,
    SegmentSpan,
)
from backend.app.schemas.edit_session import AppendSegmentsRequest, CheckpointState
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    RenderBlock,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ReferenceBindingOverride,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    InitializeEditSessionRequest,
    PreviewRequest,
    RenderProfile,
    ReorderSegmentsRequest,
    StandardizationPreviewRequest,
    SwapSegmentsRequest,
    UpdateEdgeRequest,
    UpdateSegmentRequest,
    VoiceBinding,
)
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.block_render_asset_persister import BlockRenderAssetPersister
from backend.app.services.block_render_request_builder import BlockRenderRequestBuilder
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.render_execution_plan import ExecutionPlan, ExecutionUnit, FormalBlockPlan
from backend.app.services.render_job_service import RenderJobService, RenderPlan
from backend.app.services.reference_binding import build_binding_key
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.types import ModelInstance, ModelPreset


class _FakeVoiceService:
    def get_voice(self, voice_name: str) -> VoiceProfile:
        return VoiceProfile(
            name=voice_name,
            model_instance_id=f"{voice_name}-model",
            preset_id="default",
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

    def build_reference_context(
        self,
        resolved_context: ResolvedRenderContext,
        *,
        progress_callback=None,
    ) -> ReferenceContext:
        if callable(progress_callback):
            progress_callback(
                {
                    "status": "preparing",
                    "progress": 0.5,
                    "message": "参考上下文准备中",
                }
            )
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

    def render_segment_base(self, segment, context, *, progress_callback=None) -> SegmentRenderAssetPayload:
        if callable(progress_callback):
            progress_callback(
                {
                    "status": "inferencing",
                    "progress": 0.5,
                    "message": f"正在推理段 {segment.order_key}",
                    "current_segment": 0,
                    "total_segments": 1,
                }
            )
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
        del context
        if self.fail_boundary:
            raise RuntimeError("boundary render failed")
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
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace=None,
        )


class _FakeBlockAdapter:
    def __init__(
        self,
        *,
        cancellation_checker=None,
        segment_asset_callback=None,
        fail_render: bool = False,
        fail_boundary: bool = False,
        gate: threading.Event | None = None,
    ) -> None:
        self._cancellation_checker = cancellation_checker
        self._segment_asset_callback = segment_asset_callback
        self._fail_render = fail_render
        self._fail_boundary = fail_boundary
        self._gate = gate

    def render_block(self, request):
        gate = getattr(self, "_gate", None)
        cancellation_checker = getattr(self, "_cancellation_checker", None)
        segment_asset_callback = getattr(self, "_segment_asset_callback", None)
        fail_render = getattr(self, "_fail_render", False)
        fail_boundary = getattr(self, "_fail_boundary", False)

        if gate is not None:
            gate.wait(timeout=2)
        if callable(cancellation_checker) and cancellation_checker():
            raise RuntimeError("Block rendering cancelled.")
        if fail_render:
            raise RuntimeError("segment render failed")
        audio: list[float] = []
        spans: list[SegmentSpan] = []
        outputs: list[SegmentOutput] = []
        boundary_results: list[BoundaryResult] = []
        cursor = 0
        for index, segment in enumerate(request.block.segments, start=1):
            asset = SegmentRenderAssetPayload(
                render_asset_id=f"base-{segment.segment_id}",
                segment_id=segment.segment_id,
                render_version=segment.render_version or 1,
                semantic_tokens=[1, 2],
                phone_ids=[11, 12],
                decoder_frame_count=1,
                audio_sample_count=2,
                left_margin_sample_count=0,
                core_sample_count=2,
                right_margin_sample_count=0,
                left_margin_audio=np.zeros(0, dtype=np.float32),
                core_audio=np.asarray([index / 10.0, index / 10.0], dtype=np.float32),
                right_margin_audio=np.zeros(0, dtype=np.float32),
                trace=None,
            )
            if callable(segment_asset_callback):
                segment_asset_callback(asset, segment, False)
            audio.extend([index / 10.0, index / 10.0])
            span = SegmentSpan(
                segment_id=segment.segment_id,
                sample_start=cursor,
                sample_end=cursor + 2,
                precision="exact",
            )
            spans.append(span)
            outputs.append(
                SegmentOutput(
                    segment_id=segment.segment_id,
                    sample_span=span,
                    source="adapter_exact",
                )
            )
            cursor += 2
            if index < len(request.block.segments):
                edge_control = request.edge_controls[index - 1]
                audio.append(0.05 * index)
                boundary_results.append(
                    BoundaryResult(
                        edge_id=edge_control.edge_id,
                        mode="fallback",
                        sample_span=(cursor, cursor + 1),
                        diagnostics={"implementation": "fake-block-adapter"},
                    )
                )
                cursor += 1
        if fail_boundary:
            raise RuntimeError("boundary render failed")
        return BlockRenderResult(
            block_id=request.block.block_id,
            segment_ids=[segment.segment_id for segment in request.block.segments],
            sample_rate=32000,
            audio=audio,
            audio_sample_count=len(audio),
            segment_alignment_mode="exact",
            segment_outputs=outputs,
            segment_spans=spans,
            boundary_results=boundary_results,
            join_report=JoinReport(
                requested_policy=request.join_policy,
                applied_mode=request.join_policy,
                enhancement_applied=False,
                implementation="fake-block-adapter",
            ),
            adapter_trace={"request_id": request.request_id},
        )


def _build_block_first_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(
        AdapterDefinition(
            adapter_id="gpt_sovits_local",
            display_name="gpt_sovits_local",
            adapter_family="gpt",
            runtime_kind="local_in_process",
            capabilities=AdapterCapabilities(
                block_render=True,
                exact_segment_output=True,
                segment_level_voice_binding=True,
            ),
            block_limits=AdapterBlockLimits(
                max_block_seconds=40,
                max_block_chars=300,
                max_segment_count=50,
                max_payload_bytes=1024 * 1024,
            ),
        )
    )
    return registry


def _build_block_first_model_registry(tmp_path):
    registry_root = tmp_path / "tts-registry"
    registry = ModelRegistry(registry_root)
    registry.replace_models(
        [
            ModelInstance(
                model_instance_id="demo-model",
                adapter_id="gpt_sovits_local",
                source_type="local_package",
                display_name="Demo Model",
                status="ready",
                storage_mode="managed",
                instance_assets={"bert": {"path": "pretrained/bert.bin", "fingerprint": "bert-fp"}},
                endpoint=None,
                account_binding=None,
                presets=[
                    ModelPreset(
                        preset_id="default",
                        display_name="Default",
                        kind="imported",
                        status="ready",
                        fixed_fields={},
                        defaults={
                            "speed": 1.0,
                            "top_k": 15,
                            "top_p": 1.0,
                            "temperature": 1.0,
                            "noise_scale": 0.35,
                            "reference_text": "测试参考文本",
                            "reference_language": "zh",
                        },
                        preset_assets={
                            "gpt_weight": {"path": "weights/demo.ckpt", "fingerprint": "gpt-fp"},
                            "sovits_weight": {"path": "weights/demo.pth", "fingerprint": "sovits-fp"},
                            "reference_audio": {"path": "refs/demo.wav", "fingerprint": "ref-fp"},
                        },
                        fingerprint="preset-fp",
                    )
                ],
                fingerprint="model-fp",
            )
        ]
    )
    return registry


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
        export_root=tmp_path / "exports",
        staging_ttl_seconds=60,
    )
    runtime = EditSessionRuntime()
    inference_runtime = InferenceRuntimeController()
    session_service = EditSessionService(
        repository=repository,
        asset_store=asset_store,
        runtime=runtime,
        voice_service=_FakeVoiceService(),
    )
    gateway = EditableInferenceGateway(
        _FakeEditableBackend(fail_render=fail_render, fail_boundary=fail_boundary, gate=gate)
    )
    adapter_registry = _build_block_first_adapter_registry()
    model_registry = _build_block_first_model_registry(tmp_path)
    block_render_request_builder = BlockRenderRequestBuilder(adapter_registry=adapter_registry)
    block_render_asset_persister = BlockRenderAssetPersister(asset_store=asset_store)
    block_adapter_selector = lambda adapter_id, **kwargs: _FakeBlockAdapter(
        cancellation_checker=kwargs.get("cancellation_checker"),
        segment_asset_callback=kwargs.get("segment_asset_callback"),
        fail_render=fail_render,
        fail_boundary=fail_boundary,
        gate=gate,
    )
    return RenderJobService(
        repository=repository,
        asset_store=asset_store,
        runtime=runtime,
        inference_runtime=inference_runtime,
        session_service=session_service,
        gateway=gateway,
        block_planner=block_planner,
        model_registry=model_registry,
        adapter_registry=adapter_registry,
        block_render_request_builder=block_render_request_builder,
        block_render_asset_persister=block_render_asset_persister,
        block_adapter_selector=block_adapter_selector,
        run_jobs_in_background=run_jobs_in_background,
    )


def test_run_transaction_routes_initialize_to_block_first_pipeline(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    steps: list[str] = []
    plan = RenderPlan(
        job_id="job-block-first-init",
        job_kind="initialize",
        document_id="doc-1",
        request=InitializeEditSessionRequest(raw_text="第一句。", voice_id="demo"),
    )
    monkeypatch.setattr(
        service,
        "_run_initialize_block_first",
        lambda value: steps.append(f"block-first-initialize:{id(value)}"),
        raising=False,
    )

    service._run_transaction(plan)

    assert steps == [f"block-first-initialize:{id(plan)}"]


def test_run_transaction_routes_edit_to_block_first_pipeline(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    steps: list[str] = []
    plan = RenderPlan(
        job_id="job-block-first-edit",
        job_kind="segment_update",
        document_id="doc-1",
        request=InitializeEditSessionRequest(raw_text="第一句。", voice_id="demo"),
        document_version=2,
    )
    monkeypatch.setattr(
        service,
        "_run_edit_block_first",
        lambda value: steps.append(f"block-first-edit:{id(value)}"),
        raising=False,
    )

    service._run_transaction(plan)

    assert steps == [f"block-first-edit:{id(plan)}"]


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
    assert snapshot.composition_manifest_id is None


def test_run_initialize_job_single_segment_commits_formal_assets_timeline_and_changed_blocks(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)

    snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)  # noqa: SLF001
    job = service.get_job(accepted.job.job_id)

    assert len(snapshot.segments) == 1
    assert snapshot.segments[0].render_asset_id is not None
    assert service._asset_store.segment_asset_path(snapshot.segments[0].render_asset_id).exists()  # noqa: SLF001
    assert len(timeline.segment_entries) == 1
    assert len(timeline.block_entries) == 1
    assert job is not None
    assert job.changed_block_asset_ids == [timeline.block_entries[0].block_asset_id]
    assert service._asset_store.block_asset_path(job.changed_block_asset_ids[0]).exists()  # noqa: SLF001


def test_block_first_initialize_commits_head_timeline_block_assets_and_reusable_base_assets_in_timeline_order(tmp_path):
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

    class _PersistingBaseAssetAdapter(_FakeBlockAdapter):
        def __init__(self, *, segment_asset_callback):
            self._segment_asset_callback = segment_asset_callback

        def render_block(self, request):
            for index, segment in enumerate(request.block.segments, start=1):
                self._segment_asset_callback(
                    SegmentRenderAssetPayload(
                        render_asset_id=f"base-{segment.segment_id}",
                        segment_id=segment.segment_id,
                        render_version=1,
                        semantic_tokens=[index, index + 1],
                        phone_ids=[10 + index, 20 + index],
                        decoder_frame_count=3,
                        audio_sample_count=4,
                        left_margin_sample_count=1,
                        core_sample_count=2,
                        right_margin_sample_count=1,
                        left_margin_audio=np.asarray([0.01 * index], dtype=np.float32),
                        core_audio=np.asarray([0.1 * index, 0.1 * index], dtype=np.float32),
                        right_margin_audio=np.asarray([0.02 * index], dtype=np.float32),
                        trace={"kind": "base"},
                    ),
                    segment,
                    False,
                )
            return super().render_block(request)

    service._block_adapter_selector = (  # noqa: SLF001
        lambda adapter_id, **kwargs: _PersistingBaseAssetAdapter(segment_asset_callback=kwargs["segment_asset_callback"])
    )

    service.run_initialize_job(accepted.job.job_id)

    snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)  # noqa: SLF001
    job = service.get_job(accepted.job.job_id)

    assert snapshot.document_version == 1
    assert snapshot.snapshot_kind == "head"
    assert snapshot.timeline_manifest_id == timeline.timeline_manifest_id
    assert len(timeline.block_entries) == 2
    assert job is not None
    assert job.changed_block_asset_ids == [entry.block_asset_id for entry in timeline.block_entries]

    for block_entry in timeline.block_entries:
        assert service._asset_store.block_asset_path(block_entry.block_asset_id).exists()  # noqa: SLF001

    for segment in snapshot.segments:
        assert segment.base_render_asset_id == f"base-{segment.segment_id}"
        assert service._asset_store.segment_asset_path(segment.base_render_asset_id).exists()  # noqa: SLF001


def test_build_default_configuration_writes_custom_reference_into_binding_override_map():
    render_profile, voice_binding = RenderJobService._build_default_configuration(  # noqa: SLF001
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
            model_id="model-a",
            reference_source="custom",
            reference_audio_path="custom.wav",
            reference_text="自定义参考",
            reference_language="ja",
        )
    )

    binding_key = build_binding_key(voice_id=voice_binding.voice_id, model_key=voice_binding.model_key)

    assert render_profile.reference_overrides_by_binding[binding_key].reference_audio_path == "custom.wav"
    assert render_profile.reference_audio_path is None
    assert render_profile.reference_text is None
    assert render_profile.reference_language is None


def test_initialize_request_noise_scale_enters_new_render_context():
    request = InitializeEditSessionRequest(
        raw_text="第一句。",
        voice_id="demo",
        noise_scale=0.48,
    )

    render_profile, _ = RenderJobService._build_default_configuration(request)  # noqa: SLF001
    resolved_context = RenderJobService._build_resolved_context_from_request(request)  # noqa: SLF001

    assert render_profile.noise_scale == 0.48
    assert resolved_context.noise_scale == 0.48


def test_build_resolved_context_from_request_keeps_projected_model_binding_metadata():
    request = InitializeEditSessionRequest(
        raw_text="第一句。",
        voice_id="demo",
        model_id="legacy-model",
    )
    projected_voice = VoiceProfile(
        name="demo",
        model_instance_id="model-demo",
        preset_id="preset-default",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="fake.wav",
        ref_text="参考文本",
        ref_lang="zh",
        defaults=VoiceDefaults(),
    )

    resolved_context = RenderJobService._build_resolved_context_from_request(  # noqa: SLF001
        request,
        projected_voice=projected_voice,
    )

    assert resolved_context.resolved_voice_binding is not None
    assert resolved_context.resolved_voice_binding.model_instance_id == "model-demo"
    assert resolved_context.resolved_voice_binding.preset_id == "preset-default"
    assert resolved_context.resolved_voice_binding.gpt_path == "demo.ckpt"
    assert resolved_context.resolved_voice_binding.sovits_path == "demo.pth"


def test_get_segment_context_prefers_voice_preset_over_initialize_request_fallback(tmp_path):
    service = _build_service(tmp_path)
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                stem="第一句",
                text_language="zh",
                terminal_raw="。",
                terminal_closer_suffix="",
                terminal_source="original",
            )
        ],
        edges=[],
        groups=[],
        render_profiles=[
            RenderProfile(
                render_profile_id="profile-session",
                scope="session",
                name="session",
                reference_overrides_by_binding={},
            )
        ],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="demo",
                model_key="gpt-sovits-v2",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )
    plan = RenderPlan(
        job_id="job-1",
        job_kind="initialize",
        document_id="doc-1",
        request=InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
            reference_source="preset",
            reference_audio_path="request.wav",
            reference_text="请求参考",
            reference_language="en",
        ),
    )

    context = service._get_segment_context(  # noqa: SLF001
        plan=plan,
        snapshot=snapshot,
        segment=snapshot.segments[0],
    )

    assert context.reference_audio_path == "fake.wav"
    assert context.reference_text == "参考文本"
    assert context.reference_language == "zh"


def test_get_snapshot_source_text_prefers_initialize_request_raw_text(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。\n第二句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()

    assert snapshot.session_status == "ready"
    assert snapshot.source_text == "第一句。\n第二句。"


def test_collect_changed_segment_ids_detects_session_reference_asset_switch(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    head_snapshot = service._session_service.get_head_snapshot()  # noqa: SLF001
    binding_key = build_binding_key(voice_id="demo", model_key="gpt-sovits-v2")
    asset_a = service._session_service.create_session_reference_asset(  # noqa: SLF001
        filename="custom-a.wav",
        payload=b"RIFFcustom-a",
        binding_key=binding_key,
        reference_text="会话覆盖",
        reference_language="zh",
    )
    asset_b = service._session_service.create_session_reference_asset(  # noqa: SLF001
        filename="custom-b.wav",
        payload=b"RIFFcustom-b",
        binding_key=binding_key,
        reference_text="会话覆盖",
        reference_language="zh",
    )
    before_snapshot = head_snapshot.model_copy(
        deep=True,
        update={
            "render_profiles": [
                head_snapshot.render_profiles[0].model_copy(
                    deep=True,
                    update={
                        "reference_overrides_by_binding": {
                            binding_key: ReferenceBindingOverride(
                                session_reference_asset_id=asset_a.reference_asset_id,
                                reference_audio_path=asset_a.audio_path,
                                reference_text="会话覆盖",
                                reference_language="zh",
                            )
                        }
                    },
                )
            ]
        },
    )
    after_snapshot = before_snapshot.model_copy(
        deep=True,
        update={
            "render_profiles": [
                before_snapshot.render_profiles[0].model_copy(
                    deep=True,
                    update={
                        "reference_overrides_by_binding": {
                            binding_key: ReferenceBindingOverride(
                                session_reference_asset_id=asset_b.reference_asset_id,
                                reference_audio_path=asset_b.audio_path,
                                reference_text="会话覆盖",
                                reference_language="zh",
                            )
                        }
                    },
                )
            ]
        },
    )

    changed_segment_ids = service._collect_changed_segment_ids(  # noqa: SLF001
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )

    assert changed_segment_ids == {before_snapshot.segments[0].segment_id}


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
    assert [segment.display_text for segment in snapshot.segments] == [
        "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。",
        "他放下话筒，摸着胡须，琢磨起来。",
        "不，他太愚蠢了。",
        "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。",
        "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。",
    ]
    assert snapshot.total_segment_count == 5
    assert snapshot.total_edge_count == 4


def test_run_initialize_job_supports_english_period_in_zh_period_segment_boundary_mode(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="Hello world.\nNext line.",
            voice_id="demo",
            text_language="en",
            segment_boundary_mode="zh_period",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()

    assert snapshot.session_status == "ready"
    assert [segment.display_text for segment in snapshot.segments] == [
        "Hello world.",
        "Next line.",
    ]
    assert snapshot.total_segment_count == 2
    assert snapshot.total_edge_count == 1


def test_run_initialize_job_segments_initialized_event_includes_terminal_capsule_fields(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text='第一句？！\n第二句”',
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    events = service._runtime._events[accepted.job.job_id]  # noqa: SLF001
    payload = next(event["data"] for event in events if event["event"] == "segments_initialized")

    assert payload["segments"] == [
        {
            "segment_id": payload["segments"][0]["segment_id"],
            "order_key": 1,
            "stem": "第一句",
            "display_text": "第一句？！",
            "text_language": "auto",
            "terminal_raw": "？！",
            "terminal_closer_suffix": "",
            "terminal_source": "original",
            "detected_language": "zh",
            "inference_exclusion_reason": "none",
            "render_status": "pending",
        },
        {
            "segment_id": payload["segments"][1]["segment_id"],
            "order_key": 2,
            "stem": "第二句",
            "display_text": '第二句。”',
            "text_language": "auto",
            "terminal_raw": "",
            "terminal_closer_suffix": "”",
            "terminal_source": "synthetic",
            "detected_language": "zh",
            "inference_exclusion_reason": "none",
            "render_status": "pending",
        },
    ]


def test_get_standardization_preview_response_paginates_and_returns_structured_preview_fields(tmp_path):
    service = _build_service(tmp_path)

    response = service.get_standardization_preview_response(
        StandardizationPreviewRequest(
            raw_text='第一句？！\nSecond sentence!\n第三句”',
            text_language="auto",
            segment_limit=2,
        )
    )

    assert response.analysis_stage == "complete"
    assert response.total_segments == 3
    assert response.next_cursor == 2
    assert response.resolved_document_language == "zh"
    assert response.language_detection_source == "auto"
    assert [segment.order_key for segment in response.segments] == [1, 2]
    assert response.segments[0].stem == "第一句"
    assert response.segments[0].display_text == "第一句？！"
    assert response.segments[0].terminal_raw == "？！"
    assert response.segments[0].detected_language == "zh"
    assert response.segments[0].inference_exclusion_reason == "none"
    assert response.segments[1].stem == "Second sentence"
    assert response.segments[1].display_text == "Second sentence!"
    assert response.segments[1].detected_language == "en"
    assert response.segments[1].inference_exclusion_reason == "other_language_segment"
    assert not hasattr(response.segments[0], "canonical_text")


def test_get_standardization_preview_response_light_stage_keeps_display_text_without_language_meta(tmp_path):
    service = _build_service(tmp_path)

    response = service.get_standardization_preview_response(
        StandardizationPreviewRequest(
            raw_text='第一句？！\n第三句”',
            text_language="auto",
            include_language_analysis=False,
        )
    )

    assert response.analysis_stage == "light"
    assert response.segments[0].stem == "第一句"
    assert response.segments[0].display_text == "第一句？！"
    assert response.segments[0].terminal_raw == "？！"
    assert response.segments[0].detected_language is None
    assert response.segments[0].inference_exclusion_reason is None
    assert response.segments[1].stem == "第三句"
    assert response.segments[1].display_text == "第三句。”"
    assert response.segments[1].terminal_closer_suffix == "”"


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


def test_run_initialize_job_logs_traceback_when_render_raises(tmp_path, monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            return None

        def exception(self, message, *args):
            logged.append((message, args))

    monkeypatch.setattr("backend.app.services.render_job_service.render_job_logger", _FakeLogger())
    service = _build_service(tmp_path, fail_render=True)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)

    assert logged == [
        (
            "后台渲染作业失败 job_kind={} job_id={} document_id={} phase={} reason={}",
            ("initialize", accepted.job.job_id, accepted.job.document_id, "run_initialize_job", "segment render failed"),
        )
    ]


def test_run_edit_job_logs_traceback_when_render_raises(tmp_path, monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            return None

        def exception(self, message, *args):
            logged.append((message, args))

    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_snapshot()
    assert snapshot is not None
    rerender = service.create_rerender_segment_job(snapshot.segments[0].segment_id)

    class _AlwaysFailingAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            raise RuntimeError("edit render failed")

    monkeypatch.setattr("backend.app.services.render_job_service.render_job_logger", _FakeLogger())
    service._block_adapter_selector = lambda adapter_id, **kwargs: _AlwaysFailingAdapter(
        cancellation_checker=kwargs.get("cancellation_checker"),
        segment_asset_callback=kwargs.get("segment_asset_callback"),
    )  # noqa: SLF001

    service.run_edit_job(rerender.job.job_id)

    assert logged == [
        (
            "后台渲染作业失败 job_kind={} job_id={} document_id={} phase={} reason={}",
            ("segment_rerender", rerender.job.job_id, rerender.job.document_id, "run_edit_job", "edit render failed"),
        )
    ]


def test_run_initialize_job_enters_rendering_state_while_block_adapter_is_waiting(tmp_path):
    gate = threading.Event()
    service = _build_service(tmp_path, gate=gate)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )

    worker = threading.Thread(target=service.run_initialize_job, args=(accepted.job.job_id,), daemon=True)
    worker.start()

    deadline = time.time() + 2
    job = service.get_job(accepted.job.job_id)
    while time.time() < deadline and (job is None or job.status != "rendering"):
        time.sleep(0.01)
        job = service.get_job(accepted.job.job_id)

    assert job is not None
    assert job.status == "rendering"
    assert job.progress > 0.0

    gate.set()
    worker.join(timeout=2)

    final_job = service.get_job(accepted.job.job_id)
    assert final_job is not None
    assert final_job.status == "completed"
    assert final_job.progress == 1.0


def test_prepare_updates_job_progress_from_reference_context_callback(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    plan = RenderPlan(
        job_id=accepted.job.job_id,
        job_kind="initialize",
        document_id=accepted.job.document_id,
        request=InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        ),
    )

    service._prepare(plan)  # noqa: SLF001

    job = service.get_job(accepted.job.job_id)
    assert job is not None
    assert job.status == "preparing"
    assert job.progress > 0.05
    assert job.progress < 0.2
    assert job.message == "文本切分完成，共 2 段。"


def test_prepare_progress_callback_preserves_progress_when_heartbeat_has_no_progress(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="demo",
        )
    )
    callback = service._build_prepare_progress_callback(  # noqa: SLF001
        job_id=accepted.job.job_id,
        default_message="正在准备参考上下文。",
    )
    service._runtime.update_job(accepted.job.job_id, progress=0.13, message="初始消息")  # noqa: SLF001

    callback(
        {
            "status": "preparing",
            "message": "仍在准备参考上下文。",
        }
    )

    job = service.get_job(accepted.job.job_id)
    assert job is not None
    assert job.progress == 0.13
    assert job.message == "仍在准备参考上下文。"


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
    assert not any((tmp_path / "assets" / "formal" / "segments").rglob("audio.wav"))
    assert not any((tmp_path / "assets" / "formal" / "boundaries").rglob("audio.wav"))
    assert not any((tmp_path / "assets" / "formal" / "compositions").rglob("*.wav"))


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
    initial_render_asset_ids = {segment.segment_id: segment.render_asset_id for segment in initial_snapshot.segments}
    composed_block_ids: list[str] = []
    original_compose_block = service._composition_builder.compose_block

    def _record_compose_block(*args, **kwargs):
        composed_block_ids.append(kwargs["block_id"])
        return original_compose_block(*args, **kwargs)

    monkeypatch.setattr(service._composition_builder, "compose_block", _record_compose_block)

    edit_job = service.create_update_segment_job(
        target_segment_id,
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(edit_job.job.job_id)
    updated_snapshot = service.get_head_snapshot()
    job = service.get_job(edit_job.job.job_id)

    assert composed_block_ids == []
    assert job is not None
    assert len(job.changed_block_asset_ids) == 1
    assert untouched_block_id not in job.changed_block_asset_ids
    assert updated_snapshot.segments[2].render_asset_id == initial_render_asset_ids[updated_snapshot.segments[2].segment_id]


def test_edge_pause_update_timeline_commit_only_reports_newly_composed_block_assets(tmp_path):
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
    edge_id = initial_snapshot.edges[0].edge_id

    assert len(initial_snapshot.block_ids) == 2

    edit_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(edit_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    timeline_committed = next(
        event["data"]
        for event in service._runtime._events[edit_job.job.job_id]  # noqa: SLF001
        if event["event"] == "timeline_committed"
    )

    assert updated_snapshot.block_ids[0] != initial_snapshot.block_ids[0]
    assert updated_snapshot.block_ids[1] == initial_snapshot.block_ids[1]
    assert timeline_committed["changed_block_asset_ids"] == [updated_snapshot.block_ids[0]]


def test_edge_pause_update_skips_segment_rerender_and_updates_timeline_sample_span(tmp_path, monkeypatch):
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
    initial_timeline = service._asset_store.load_timeline_manifest(initial_snapshot.timeline_manifest_id)  # noqa: SLF001
    initial_render_asset_ids = {segment.segment_id: segment.render_asset_id for segment in initial_snapshot.segments}
    edge_id = initial_snapshot.edges[0].edge_id

    def _unexpected_segment_render(*args, **kwargs):
        raise AssertionError("edge pause update should not rerender segment assets")

    monkeypatch.setattr(service._gateway, "render_segment_base", _unexpected_segment_render)

    edit_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(edit_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    updated_timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert [segment.render_asset_id for segment in updated_snapshot.segments] == [
        initial_render_asset_ids[segment.segment_id] for segment in updated_snapshot.segments
    ]
    assert updated_timeline.playable_sample_span[1] > initial_timeline.playable_sample_span[1]


def test_edge_pause_update_handles_previous_parent_block_without_exact_reuse_match(tmp_path, monkeypatch):
    service = _build_service(
        tmp_path,
        block_planner=BlockPlanner(
            sample_rate=1,
            min_block_seconds=3,
            max_block_seconds=1000,
            max_segment_count=50,
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
    initial_timeline = service._asset_store.load_timeline_manifest(initial_snapshot.timeline_manifest_id)  # noqa: SLF001
    edge_id = initial_snapshot.edges[0].edge_id

    assert [entry.segment_ids for entry in initial_timeline.block_entries] == [
        [segment.segment_id for segment in initial_snapshot.segments]
    ]

    def _unexpected_segment_render(*args, **kwargs):
        raise AssertionError("edge pause update should not rerender segment assets")

    monkeypatch.setattr(service._gateway, "render_segment_base", _unexpected_segment_render)

    edit_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )

    service.run_edit_job(edit_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    updated_timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert updated_snapshot.edges[0].pause_duration_seconds == 0.8
    assert [entry.segment_ids for entry in updated_timeline.block_entries] == [
        [updated_snapshot.segments[0].segment_id, updated_snapshot.segments[1].segment_id],
        [updated_snapshot.segments[2].segment_id],
    ]


def test_block_first_middle_segment_update_keeps_timeline_blocks_in_document_order(tmp_path):
    service = _build_service(
        tmp_path,
        block_planner=BlockPlanner(
            sample_rate=1,
            min_block_seconds=100,
            max_block_seconds=1000,
            max_segment_count=50,
        ),
    )
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。第四句。第五句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)

    initial_snapshot = service.get_head_snapshot()
    initial_timeline = service._asset_store.load_timeline_manifest(initial_snapshot.timeline_manifest_id)  # noqa: SLF001
    assert [entry.segment_ids for entry in initial_timeline.block_entries] == [
        [segment.segment_id for segment in initial_snapshot.segments]
    ]

    rerender = service.create_update_segment_job(
        initial_snapshot.segments[2].segment_id,
        UpdateSegmentRequest(
            text_patch={
                "stem": "第三句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(rerender.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    updated_timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert [
        segment_id
        for entry in updated_timeline.block_entries
        for segment_id in entry.segment_ids
    ] == [segment.segment_id for segment in updated_snapshot.segments]
    assert [entry.segment_id for entry in updated_timeline.segment_entries] == [
        segment.segment_id for segment in updated_snapshot.segments
    ]


def test_edge_pause_update_persists_committed_metadata_into_render_job_state(tmp_path):
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
    edge_id = initial_snapshot.edges[0].edge_id

    edit_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(edit_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    job = service.get_job(edit_job.job.job_id)
    stored_job = service._repository.get_render_job(edit_job.job.job_id)  # noqa: SLF001

    assert job is not None
    assert stored_job is not None
    assert job.committed_document_version == updated_snapshot.document_version
    assert job.committed_timeline_manifest_id == updated_snapshot.timeline_manifest_id
    assert job.changed_block_asset_ids == [updated_snapshot.block_ids[0]]
    assert stored_job.committed_document_version == updated_snapshot.document_version
    assert stored_job.committed_timeline_manifest_id == updated_snapshot.timeline_manifest_id
    assert stored_job.changed_block_asset_ids == [updated_snapshot.block_ids[0]]


def test_edge_pause_update_does_not_build_reference_context_again(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    edge_id = service.get_head_snapshot().edges[0].edge_id
    build_context_calls = 0
    original_build_reference_context = service._gateway.build_reference_context

    def _count_build_reference_context(*args, **kwargs):
        nonlocal build_context_calls
        build_context_calls += 1
        return original_build_reference_context(*args, **kwargs)

    monkeypatch.setattr(
        service._gateway,
        "build_reference_context",
        _count_build_reference_context,
    )

    edit_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(edit_job.job.job_id)

    assert build_context_calls == 0


def test_segment_swap_does_not_build_reference_context_again(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()
    build_context_calls = 0
    original_build_reference_context = service._gateway.build_reference_context

    def _count_build_reference_context(*args, **kwargs):
        nonlocal build_context_calls
        build_context_calls += 1
        return original_build_reference_context(*args, **kwargs)

    monkeypatch.setattr(
        service._gateway,
        "build_reference_context",
        _count_build_reference_context,
    )

    edit_job = service.create_swap_segments_job(
        SwapSegmentsRequest(
            first_segment_id=snapshot.segments[0].segment_id,
            second_segment_id=snapshot.segments[2].segment_id,
        )
    )
    service.run_edit_job(edit_job.job.job_id)

    assert build_context_calls == 0


def test_segment_reorder_only_builds_boundary_context_when_boundary_asset_must_be_rebuilt(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()
    build_context_calls = 0
    original_build_reference_context = service._gateway.build_reference_context

    def _count_build_reference_context(*args, **kwargs):
        nonlocal build_context_calls
        build_context_calls += 1
        return original_build_reference_context(*args, **kwargs)

    monkeypatch.setattr(
        service._gateway,
        "build_reference_context",
        _count_build_reference_context,
    )

    edit_job = service.create_reorder_segments_job(
        ReorderSegmentsRequest(
            base_document_version=snapshot.document_version,
            ordered_segment_ids=[
                snapshot.segments[2].segment_id,
                snapshot.segments[0].segment_id,
                snapshot.segments[1].segment_id,
            ],
        )
    )
    service.run_edit_job(edit_job.job.job_id)

    assert build_context_calls == 1


def test_edge_pause_update_succeeds_when_standalone_boundary_asset_is_missing(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    edge_id = service.get_head_snapshot().edges[0].edge_id

    strategy_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(boundary_strategy="crossfade_only"),
    )
    service.run_edit_job(strategy_job.job.job_id)

    strategy_snapshot = service.get_head_snapshot()
    left_segment = strategy_snapshot.segments[0]
    right_segment = strategy_snapshot.segments[1]
    edge = strategy_snapshot.edges[0]
    boundary_asset_id = build_boundary_asset_id(
        left_segment_id=edge.left_segment_id,
        left_render_version=left_segment.render_version,
        right_segment_id=edge.right_segment_id,
        right_render_version=right_segment.render_version,
        edge_version=edge.edge_version,
        boundary_strategy=edge.effective_boundary_strategy or edge.boundary_strategy,
    )
    boundary_dir = tmp_path / "assets" / "formal" / "boundaries" / boundary_asset_id
    if boundary_dir.exists():
        shutil.rmtree(boundary_dir)
    assert not boundary_dir.exists()

    pause_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )

    service.run_edit_job(pause_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    assert updated_snapshot.edges[0].pause_duration_seconds == 0.8


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
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    queued_job = service._queued_edit_jobs[edit_job.job.job_id]  # noqa: SLF001

    assert queued_job.earliest_changed_order_key == 1
    assert queued_job.timeline_reflow_required is True
    assert queued_job.change_reason == "segment_update"


def test_run_initialize_job_persists_structured_segment_text_fields_without_legacy_raw_or_normalized_text(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text='第一句？！第二句”',
            voice_id="demo",
        )
    )

    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()

    assert [segment.stem for segment in snapshot.segments] == ["第一句", "第二句"]
    assert [segment.display_text for segment in snapshot.segments] == ['第一句？！', '第二句。”']
    assert not hasattr(snapshot.segments[0], "raw_text")
    assert not hasattr(snapshot.segments[0], "normalized_text")


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
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(edit_job.job.job_id)

    assert captured == {
        "earliest_changed_order_key": 1,
        "timeline_reflow_required": True,
        "change_reason": "segment_update",
    }


def test_block_first_pause_only_update_recomposes_dirty_block_without_adapter_inference(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    initial_snapshot = service.get_head_snapshot()
    edge_id = initial_snapshot.edges[0].edge_id
    adapter_calls: list[list[str]] = []

    class _CountingBlockAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            adapter_calls.append(list(request.block.segment_ids))
            return super().render_block(request)

    service._block_adapter_selector = lambda adapter_id, **kwargs: _CountingBlockAdapter()  # noqa: SLF001

    pause_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(pause_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert adapter_calls == []
    assert updated_snapshot.edges[0].pause_duration_seconds == 0.8
    assert timeline.edge_entries[0].pause_duration_seconds == 0.8


def test_block_first_pause_only_update_reuses_boundary_audio_from_previous_block_asset(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    initial_snapshot = service.get_head_snapshot()
    edge_id = initial_snapshot.edges[0].edge_id

    monkeypatch.setattr(
        service._gateway,  # noqa: SLF001
        "render_boundary_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pause-only should not rebuild boundary asset")),
    )

    pause_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(pause_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert updated_snapshot.edges[0].pause_duration_seconds == 0.8
    assert timeline.edge_entries[0].pause_duration_seconds == 0.8


def test_block_first_pause_only_update_reuses_boundary_audio_when_block_repartitioned(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。第三句。第四句。第五句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    initial_snapshot = service.get_head_snapshot()
    edge_id = initial_snapshot.edges[0].edge_id
    original_build_blocks = service._block_planner.build_blocks  # noqa: SLF001

    def _split_into_four_plus_one(segments):
        ordered = sorted(segments, key=lambda item: item.order_key)
        if len(ordered) != 5:
            return original_build_blocks(segments)
        return [
            RenderBlock(
                block_id="block-first-four",
                segment_ids=[segment.segment_id for segment in ordered[:4]],
                start_order_key=ordered[0].order_key,
                end_order_key=ordered[3].order_key,
                estimated_sample_count=0,
            ),
            RenderBlock(
                block_id="block-last-one",
                segment_ids=[ordered[4].segment_id],
                start_order_key=ordered[4].order_key,
                end_order_key=ordered[4].order_key,
                estimated_sample_count=0,
            ),
        ]

    monkeypatch.setattr(service._block_planner, "build_blocks", _split_into_four_plus_one)  # noqa: SLF001
    monkeypatch.setattr(
        service._gateway,  # noqa: SLF001
        "render_boundary_asset",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("pause-only repartition should still reuse boundary audio from previous block asset")
        ),
    )

    pause_job = service.create_update_edge_job(
        edge_id,
        UpdateEdgeRequest(pause_duration_seconds=0.8),
    )
    service.run_edit_job(pause_job.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001

    assert updated_snapshot.edges[0].pause_duration_seconds == 0.8
    assert [entry.segment_ids for entry in timeline.block_entries] == [
        [segment.segment_id for segment in updated_snapshot.segments[:4]],
        [updated_snapshot.segments[4].segment_id],
    ]


def test_block_first_boundary_rebuild_uses_base_render_assets_when_exact_assets_are_derived(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    original_build_execution_plan = service._block_render_request_builder.build_execution_plan  # noqa: SLF001

    def _split_initialize_execution_plan(**kwargs):
        execution_plan = original_build_execution_plan(**kwargs)
        assert len(execution_plan.formal_blocks) == 1
        formal_block_plan = execution_plan.formal_blocks[0]
        assert len(formal_block_plan.execution_units) == 1
        original_unit = formal_block_plan.execution_units[0]
        split_units: list[ExecutionUnit] = []
        for segment in original_unit.request.block.segments:
            split_request = original_unit.request.model_copy(
                update={
                    "request_id": f"{original_unit.request.request_id}-{segment.segment_id}",
                    "execution_unit_id": f"{original_unit.request.execution_unit_id}-{segment.segment_id}",
                    "block": original_unit.request.block.model_copy(
                        update={
                            "block_id": f"block-{segment.segment_id}",
                            "segment_ids": [segment.segment_id],
                            "start_order_key": segment.order_key,
                            "end_order_key": segment.order_key,
                            "segments": [segment],
                            "block_text": segment.text,
                        }
                    ),
                    "edge_controls": [],
                    "boundary_contexts": [],
                    "reusable_source_assets": [
                        asset
                        for asset in original_unit.request.reusable_source_assets
                        if asset.segment_id == segment.segment_id
                    ],
                }
            )
            split_units.append(
                ExecutionUnit(
                    execution_unit_id=split_request.execution_unit_id,
                    formal_block_id=formal_block_plan.formal_block_id,
                    request=split_request,
                    segment_ids=(segment.segment_id,),
                    boundary_contexts=(),
                    reusable_source_assets=tuple(split_request.reusable_source_assets),
                    scope_policy=original_unit.scope_policy,
                    degradation_policy=original_unit.degradation_policy,
                )
            )
        return ExecutionPlan(
            formal_blocks=(
                FormalBlockPlan(
                    formal_block=formal_block_plan.formal_block,
                    execution_units=tuple(split_units),
                ),
            )
        )

    monkeypatch.setattr(service._block_render_request_builder, "build_execution_plan", _split_initialize_execution_plan)  # noqa: SLF001

    class _BoundaryRebuildAdapter(_FakeBlockAdapter):
        def __init__(self, *, segment_asset_callback):
            self._segment_asset_callback = segment_asset_callback

        def render_block(self, request):
            for segment in request.block.segments:
                base_asset = SegmentRenderAssetPayload(
                    render_asset_id=f"base-{segment.segment_id}",
                    segment_id=segment.segment_id,
                    render_version=1,
                    semantic_tokens=[1, 2, 3],
                    phone_ids=[11, 12],
                    decoder_frame_count=3,
                    audio_sample_count=3,
                    left_margin_sample_count=1,
                    core_sample_count=1,
                    right_margin_sample_count=1,
                    left_margin_audio=np.asarray([0.1], dtype=np.float32),
                    core_audio=np.asarray([0.2], dtype=np.float32),
                    right_margin_audio=np.asarray([0.3], dtype=np.float32),
                    trace={
                        "left_margin_frames": [0.1],
                        "right_margin_frames": [0.3],
                    },
                )
                self._segment_asset_callback(base_asset, segment, False)
            return super().render_block(request)

    service._block_adapter_selector = (  # noqa: SLF001
        lambda adapter_id, **kwargs: _BoundaryRebuildAdapter(segment_asset_callback=kwargs["segment_asset_callback"])
    )

    def _assert_boundary_rebuild_uses_base_assets(left_asset, right_asset, edge, context):
        del edge, context
        assert left_asset.render_asset_id == f"base-{left_asset.segment_id}"
        assert right_asset.render_asset_id == f"base-{right_asset.segment_id}"
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=left_asset.segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=right_asset.segment_id,
                right_render_version=right_asset.render_version,
                edge_version=0,
                boundary_strategy="latent_overlap_then_equal_power_crossfade",
            ),
            left_segment_id=left_asset.segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=right_asset.segment_id,
            right_render_version=right_asset.render_version,
            edge_version=0,
            boundary_strategy="latent_overlap_then_equal_power_crossfade",
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace={"rebuilt_from": "base_assets"},
        )

    monkeypatch.setattr(service._gateway, "render_boundary_asset", _assert_boundary_rebuild_uses_base_assets)  # noqa: SLF001

    service.run_initialize_job(accepted.job.job_id)

    job = service.get_job(accepted.job.job_id)
    assert job is not None
    assert job.status == "completed"


def test_block_first_initialize_persists_callback_base_render_assets(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    original_build_execution_plan = service._block_render_request_builder.build_execution_plan  # noqa: SLF001

    def _split_initialize_execution_plan(**kwargs):
        execution_plan = original_build_execution_plan(**kwargs)
        assert len(execution_plan.formal_blocks) == 1
        formal_block_plan = execution_plan.formal_blocks[0]
        original_unit = formal_block_plan.execution_units[0]
        split_units: list[ExecutionUnit] = []
        for segment in original_unit.request.block.segments:
            split_request = original_unit.request.model_copy(
                update={
                    "request_id": f"{original_unit.request.request_id}-{segment.segment_id}",
                    "execution_unit_id": f"{original_unit.request.execution_unit_id}-{segment.segment_id}",
                    "block": original_unit.request.block.model_copy(
                        update={
                            "block_id": f"block-{segment.segment_id}",
                            "segment_ids": [segment.segment_id],
                            "start_order_key": segment.order_key,
                            "end_order_key": segment.order_key,
                            "segments": [segment],
                            "block_text": segment.text,
                        }
                    ),
                    "edge_controls": [],
                    "boundary_contexts": [],
                    "reusable_source_assets": [
                        asset
                        for asset in original_unit.request.reusable_source_assets
                        if asset.segment_id == segment.segment_id
                    ],
                }
            )
            split_units.append(
                ExecutionUnit(
                    execution_unit_id=split_request.execution_unit_id,
                    formal_block_id=formal_block_plan.formal_block_id,
                    request=split_request,
                    segment_ids=(segment.segment_id,),
                    boundary_contexts=(),
                    reusable_source_assets=tuple(split_request.reusable_source_assets),
                    scope_policy=original_unit.scope_policy,
                    degradation_policy=original_unit.degradation_policy,
                )
            )
        return ExecutionPlan(
            formal_blocks=(
                FormalBlockPlan(
                    formal_block=formal_block_plan.formal_block,
                    execution_units=tuple(split_units),
                ),
            )
        )

    monkeypatch.setattr(service._block_render_request_builder, "build_execution_plan", _split_initialize_execution_plan)  # noqa: SLF001

    class _PersistingBaseAssetAdapter(_FakeBlockAdapter):
        def __init__(self, *, segment_asset_callback):
            self._segment_asset_callback = segment_asset_callback

        def render_block(self, request):
            for segment in request.block.segments:
                self._segment_asset_callback(
                    SegmentRenderAssetPayload(
                        render_asset_id=f"base-{segment.segment_id}",
                        segment_id=segment.segment_id,
                        render_version=1,
                        semantic_tokens=[1, 2, 3],
                        phone_ids=[11, 12],
                        decoder_frame_count=3,
                        audio_sample_count=3,
                        left_margin_sample_count=1,
                        core_sample_count=1,
                        right_margin_sample_count=1,
                        left_margin_audio=np.asarray([0.1], dtype=np.float32),
                        core_audio=np.asarray([0.2], dtype=np.float32),
                        right_margin_audio=np.asarray([0.3], dtype=np.float32),
                        trace={"left_margin_frames": [0.1], "right_margin_frames": [0.3]},
                    ),
                        segment,
                        False,
                    )
                callback = self._segment_asset_callback
                self._segment_asset_callback = None
                try:
                    return super().render_block(request)
                finally:
                    self._segment_asset_callback = callback

    service._block_adapter_selector = (  # noqa: SLF001
        lambda adapter_id, **kwargs: _PersistingBaseAssetAdapter(segment_asset_callback=kwargs["segment_asset_callback"])
    )

    service.run_initialize_job(accepted.job.job_id)

    snapshot = service.get_head_snapshot()
    for segment in snapshot.segments:
        assert segment.base_render_asset_id == f"base-{segment.segment_id}"
        persisted_asset = service._asset_store.load_segment_asset(segment.base_render_asset_id)  # noqa: SLF001
        assert persisted_asset.render_asset_id == segment.base_render_asset_id
        assert persisted_asset.segment_id == segment.segment_id
        assert persisted_asset.decoder_frame_count == 3

    pin_set = service._render_asset_lifecycle.collect_pin_set()  # noqa: SLF001
    assert any(asset.asset_kind == "block" for asset in pin_set.published_assets)
    assert any(asset.asset_kind == "timeline" for asset in pin_set.published_assets)
    assert {(asset.segment_id, asset.render_asset_id) for asset in pin_set.reusable_source_assets} == {
        (segment.segment_id, f"base-{segment.segment_id}")
        for segment in snapshot.segments
    }

    orphan_dir = service._asset_store.block_asset_path("orphan-block-asset")  # noqa: SLF001
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "metadata.json").write_text("{}", encoding="utf-8")
    orphan_report = service._render_asset_lifecycle.scan_orphaned_assets()  # noqa: SLF001
    assert "blocks/orphan-block-asset" in orphan_report.orphaned_relative_paths


def test_block_first_boundary_rebuild_downgrades_to_crossfade_only_when_only_exact_assets_exist(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )

    original_build_execution_plan = service._block_render_request_builder.build_execution_plan  # noqa: SLF001

    def _split_initialize_execution_plan(**kwargs):
        execution_plan = original_build_execution_plan(**kwargs)
        assert len(execution_plan.formal_blocks) == 1
        formal_block_plan = execution_plan.formal_blocks[0]
        original_unit = formal_block_plan.execution_units[0]
        split_units: list[ExecutionUnit] = []
        for segment in original_unit.request.block.segments:
            split_request = original_unit.request.model_copy(
                update={
                    "request_id": f"{original_unit.request.request_id}-{segment.segment_id}",
                    "execution_unit_id": f"{original_unit.request.execution_unit_id}-{segment.segment_id}",
                    "block": original_unit.request.block.model_copy(
                        update={
                            "block_id": f"block-{segment.segment_id}",
                            "segment_ids": [segment.segment_id],
                            "start_order_key": segment.order_key,
                            "end_order_key": segment.order_key,
                            "segments": [segment],
                            "block_text": segment.text,
                        }
                    ),
                    "edge_controls": [],
                    "boundary_contexts": [],
                    "reusable_source_assets": [
                        asset
                        for asset in original_unit.request.reusable_source_assets
                        if asset.segment_id == segment.segment_id
                    ],
                }
            )
            split_units.append(
                ExecutionUnit(
                    execution_unit_id=split_request.execution_unit_id,
                    formal_block_id=formal_block_plan.formal_block_id,
                    request=split_request,
                    segment_ids=(segment.segment_id,),
                    boundary_contexts=(),
                    reusable_source_assets=tuple(split_request.reusable_source_assets),
                    scope_policy=original_unit.scope_policy,
                    degradation_policy=original_unit.degradation_policy,
                )
            )
        return ExecutionPlan(
            formal_blocks=(
                FormalBlockPlan(
                    formal_block=formal_block_plan.formal_block,
                    execution_units=tuple(split_units),
                ),
            )
        )

    monkeypatch.setattr(service._block_render_request_builder, "build_execution_plan", _split_initialize_execution_plan)  # noqa: SLF001

    def _assert_boundary_rebuild_is_downgraded(left_asset, right_asset, edge, context):
        del left_asset, right_asset, context
        assert edge.boundary_strategy == "crossfade_only"
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=0,
                right_segment_id=edge.right_segment_id,
                right_render_version=0,
                edge_version=edge.edge_version,
                boundary_strategy="crossfade_only",
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=0,
            right_segment_id=edge.right_segment_id,
            right_render_version=0,
            edge_version=edge.edge_version,
            boundary_strategy="crossfade_only",
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace={"boundary_kind": "crossfade_only"},
        )

    monkeypatch.setattr(service._gateway, "render_boundary_asset", _assert_boundary_rebuild_is_downgraded)  # noqa: SLF001

    service.run_initialize_job(accepted.job.job_id)

    job = service.get_job(accepted.job.job_id)
    assert job is not None
    assert job.status == "completed"


def test_block_first_segment_update_warns_and_escalates_from_segment_scope_to_block_scope(tmp_path, monkeypatch):
    logged_warnings: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            logged_warnings.append((message, args))

        def exception(self, message, *args):
            return None

    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()
    attempted_scopes: list[tuple[str, list[str], str | None]] = []

    class _EscalatingAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            attempted_scopes.append((request.render_scope, list(request.block.segment_ids), request.escalated_from_scope))
            if request.render_scope == "segment":
                raise SegmentScopeUnsupported(
                    reason_code="neighbor_asset_not_reusable",
                    message="局部窗口无法安全复用增强边界。",
                    details={"segment_ids": list(request.block.segment_ids)},
                )
            return super().render_block(request)

    monkeypatch.setattr("backend.app.services.render_job_service.render_job_logger", _FakeLogger())
    service._block_adapter_selector = lambda adapter_id, **kwargs: _EscalatingAdapter()  # noqa: SLF001

    rerender = service.create_update_segment_job(
        snapshot.segments[0].segment_id,
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(rerender.job.job_id)

    job = service.get_job(rerender.job.job_id)

    assert attempted_scopes == [
        ("segment", [snapshot.segments[0].segment_id, snapshot.segments[1].segment_id], None),
        ("block", [snapshot.segments[0].segment_id, snapshot.segments[1].segment_id], "segment"),
    ]
    assert job is not None
    assert job.status == "completed"
    assert len(logged_warnings) == 1
    assert logged_warnings[0][0] == (
        "segment-scope render unsupported; escalating to block scope job_id={} block_id={} reason_code={} details={}"
    )
    assert logged_warnings[0][1][0] == rerender.job.job_id
    assert isinstance(logged_warnings[0][1][1], str) and logged_warnings[0][1][1].startswith("block-")
    assert logged_warnings[0][1][2] == "neighbor_asset_not_reusable"
    assert logged_warnings[0][1][3] == {"segment_ids": attempted_scopes[0][1]}


def test_block_first_scope_escalation_and_result_degradation_use_separate_state_fields(tmp_path, monkeypatch):
    logged_warnings: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            logged_warnings.append((message, args))

        def exception(self, message, *args):
            return None

    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()
    attempted_scopes: list[tuple[str, str | None]] = []

    class _EscalatingEstimatedAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            attempted_scopes.append((request.render_scope, request.escalated_from_scope))
            if request.render_scope == "segment":
                raise SegmentScopeUnsupported(
                    reason_code="neighbor_asset_not_reusable",
                    message="局部窗口无法安全复用增强边界。",
                )
            return BlockRenderResult(
                block_id=request.block.block_id,
                segment_ids=[segment.segment_id for segment in request.block.segments],
                sample_rate=32000,
                audio=[0.1, 0.2, 0.3, 0.4],
                audio_sample_count=4,
                segment_alignment_mode="estimated",
                segment_outputs=[],
                segment_spans=[
                    SegmentSpan(
                        segment_id=request.block.segments[0].segment_id,
                        sample_start=0,
                        sample_end=2,
                        precision="estimated",
                        confidence=0.8,
                        source="system_estimated",
                    ),
                    SegmentSpan(
                        segment_id=request.block.segments[1].segment_id,
                        sample_start=2,
                        sample_end=4,
                        precision="estimated",
                        confidence=0.7,
                        source="system_estimated",
                    ),
                ],
                join_report=JoinReport(
                    requested_policy=request.join_policy,
                    applied_mode=request.join_policy,
                    enhancement_applied=False,
                    implementation="estimated-after-escalation",
                ),
            )

    monkeypatch.setattr("backend.app.services.render_job_service.render_job_logger", _FakeLogger())
    service._block_adapter_selector = lambda adapter_id, **kwargs: _EscalatingEstimatedAdapter()  # noqa: SLF001

    rerender = service.create_update_segment_job(
        snapshot.segments[0].segment_id,
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(rerender.job.job_id)

    updated_snapshot = service.get_head_snapshot()
    updated_timeline = service._asset_store.load_timeline_manifest(updated_snapshot.timeline_manifest_id)  # noqa: SLF001
    job = service.get_job(rerender.job.job_id)

    assert attempted_scopes == [("segment", None), ("block", "segment")]
    assert [entry.segment_alignment_mode for entry in updated_timeline.block_entries] == ["estimated"]
    assert [entry.alignment_precision for entry in updated_timeline.segment_entries] == ["estimated", "estimated"]
    assert job is not None
    assert job.status == "completed"
    assert len(logged_warnings) == 1


def test_block_first_segment_update_fails_when_block_scope_also_fails(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)
    snapshot = service.get_head_snapshot()

    class _AlwaysFailingAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            if request.render_scope == "segment":
                raise SegmentScopeUnsupported(
                    reason_code="neighbor_asset_not_reusable",
                    message="局部窗口无法安全复用增强边界。",
                )
            raise BlockScopeUnsupported(
                reason_code="invalid_request_topology",
                message="块级请求仍无法成立。",
            )

    service._block_adapter_selector = lambda adapter_id, **kwargs: _AlwaysFailingAdapter()  # noqa: SLF001

    rerender = service.create_update_segment_job(
        snapshot.segments[0].segment_id,
        UpdateSegmentRequest(
            text_patch={
                "stem": "第一句已修改",
                "terminal_raw": "。",
                "terminal_closer_suffix": "",
                "terminal_source": "original",
            }
        ),
    )
    service.run_edit_job(rerender.job.job_id)

    job = service.get_job(rerender.job.job_id)

    assert job is not None
    assert job.status == "failed"
    assert "块级请求仍无法成立" in (job.message or "")


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


def test_build_preview_reads_edge_audio_from_block_when_formal_boundary_asset_is_missing(tmp_path):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    service.run_initialize_job(accepted.job.job_id)

    snapshot = service.get_head_snapshot()
    timeline = service._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)  # noqa: SLF001
    edge_id = snapshot.edges[0].edge_id
    block_id = snapshot.block_ids[0]
    edge_entry = next(entry for entry in timeline.edge_entries if entry.edge_id == edge_id)
    block_entry = next(
        entry
        for entry in timeline.block_entries
        if entry.start_sample <= edge_entry.boundary_start_sample < entry.end_sample
    )
    block_asset = service._asset_store.load_block_asset(block_id)  # noqa: SLF001
    boundary_asset_id = build_boundary_asset_id(
        left_segment_id=snapshot.edges[0].left_segment_id,
        left_render_version=snapshot.segments[0].render_version,
        right_segment_id=snapshot.edges[0].right_segment_id,
        right_render_version=snapshot.segments[1].render_version,
        edge_version=snapshot.edges[0].edge_version,
        boundary_strategy=snapshot.edges[0].effective_boundary_strategy or snapshot.edges[0].boundary_strategy,
    )
    boundary_path = service._asset_store.boundary_asset_path(boundary_asset_id)  # noqa: SLF001
    if boundary_path.exists():
        shutil.rmtree(boundary_path)
    expected_audio = block_asset.audio[
        edge_entry.boundary_start_sample - block_entry.start_sample : edge_entry.boundary_end_sample - block_entry.start_sample
    ]

    preview = service.build_preview(PreviewRequest(edge_id=edge_id))

    assert preview.preview_kind == "edge"
    assert preview.audio.size > 0
    assert np.allclose(preview.audio, expected_audio, atol=1e-4)


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


def test_initialize_job_cancel_after_first_execution_unit_becomes_cancelled_partial(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    accepted = service.create_initialize_job(
        InitializeEditSessionRequest(
            raw_text="第一句。第二句。",
            voice_id="demo",
        )
    )
    original_build_execution_plan = service._block_render_request_builder.build_execution_plan  # noqa: SLF001

    def _split_initialize_execution_plan(**kwargs):
        execution_plan = original_build_execution_plan(**kwargs)
        assert len(execution_plan.formal_blocks) == 1
        formal_block_plan = execution_plan.formal_blocks[0]
        assert len(formal_block_plan.execution_units) == 1
        original_unit = formal_block_plan.execution_units[0]
        split_units: list[ExecutionUnit] = []
        for segment in original_unit.request.block.segments:
            split_request = original_unit.request.model_copy(
                update={
                    "request_id": f"{original_unit.request.request_id}-{segment.segment_id}",
                    "execution_unit_id": f"{original_unit.request.execution_unit_id}-{segment.segment_id}",
                    "block": original_unit.request.block.model_copy(
                        update={
                            "block_id": f"block-{segment.segment_id}",
                            "segment_ids": [segment.segment_id],
                            "start_order_key": segment.order_key,
                            "end_order_key": segment.order_key,
                            "segments": [segment],
                            "block_text": segment.text,
                        }
                    ),
                    "edge_controls": [],
                    "boundary_contexts": [],
                    "reusable_source_assets": [
                        asset
                        for asset in original_unit.request.reusable_source_assets
                        if asset.segment_id == segment.segment_id
                    ],
                }
            )
            split_units.append(
                ExecutionUnit(
                    execution_unit_id=split_request.execution_unit_id,
                    formal_block_id=formal_block_plan.formal_block_id,
                    request=split_request,
                    segment_ids=(segment.segment_id,),
                    boundary_contexts=(),
                    reusable_source_assets=tuple(split_request.reusable_source_assets),
                    scope_policy=original_unit.scope_policy,
                    degradation_policy=original_unit.degradation_policy,
                )
            )
        return ExecutionPlan(
            formal_blocks=(
                FormalBlockPlan(
                    formal_block=formal_block_plan.formal_block,
                    execution_units=tuple(split_units),
                ),
            )
        )

    cancel_requested = False

    class _CancelAfterFirstExecutionUnitAdapter(_FakeBlockAdapter):
        def render_block(self, request):
            nonlocal cancel_requested
            result = super().render_block(request)
            if not cancel_requested:
                cancel_requested = True
                cancelled = service.cancel_job(accepted.job.job_id)
                assert cancelled is True
            return result

    monkeypatch.setattr(service._block_render_request_builder, "build_execution_plan", _split_initialize_execution_plan)  # noqa: SLF001
    service._block_adapter_selector = lambda adapter_id, **kwargs: _CancelAfterFirstExecutionUnitAdapter(
        cancellation_checker=kwargs.get("cancellation_checker"),
        segment_asset_callback=kwargs.get("segment_asset_callback"),
    )  # noqa: SLF001

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
