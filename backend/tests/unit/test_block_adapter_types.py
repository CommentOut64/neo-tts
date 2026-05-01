import pytest

from pydantic import ValidationError

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_types import (
    AdapterCapabilities,
    BlockPolicy,
    BlockRenderRequest,
    BlockRenderResult,
    BlockRequestBlock,
    BlockRequestSegment,
    DirtyContext,
    EdgeControl,
    JoinReport,
    ResolvedModelBinding,
    SegmentScopeUnsupported,
    SegmentOutput,
    SegmentSpan,
)


def _build_request() -> BlockRenderRequest:
    return BlockRenderRequest(
        request_id="req-1",
        document_id="doc-1",
        block=BlockRequestBlock(
            block_id="block-1",
            segment_ids=["seg-1", "seg-2"],
            start_order_key=1,
            end_order_key=2,
            estimated_sample_count=6400,
            segments=[
                BlockRequestSegment(segment_id="seg-1", order_key=1, text="第一句。", language="zh"),
                BlockRequestSegment(segment_id="seg-2", order_key=2, text="第二句。", language="zh"),
            ],
            block_text="第一句。\n第二句。",
        ),
        model_binding=ResolvedModelBinding(
            adapter_id="gpt_sovits_local",
            model_instance_id="model-1",
            preset_id="preset-1",
            resolved_assets={"gpt_weight": "weights/demo.ckpt"},
            resolved_reference={
                "reference_id": "ref-1",
                "audio_uri": "managed://references/ref-1.wav",
                "text": "参考文本",
                "language": "zh",
                "source": "preset",
                "fingerprint": "ref-fp",
            },
            resolved_parameters={"speed": 1.0},
            secret_handles={},
            binding_fingerprint="binding-fp",
        ),
        voice={"voice_id": "voice-demo"},
        model={"model_key": "gpt-sovits-v2"},
        reference={"reference_id": "ref-1"},
        synthesis={"language": "zh", "speed": 1.0},
        output_policy="prefer_exact",
        join_policy="prefer_enhanced",
        edge_controls=[
            EdgeControl(
                edge_id="edge-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
                pause_duration_seconds=0.3,
                join_policy_override="preserve_pause",
                locked=False,
            )
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-1"],
            previous_block_asset_id="block-asset-1",
            reuse_policy="prefer_reuse",
        ),
        adapter_options={
            "gpt_sovits_local": {
                "top_k": 15,
                "top_p": 1.0,
                "temperature": 1.0,
                "noise_scale": 0.35,
            }
        },
        block_policy=BlockPolicy(
            min_block_seconds=20,
            max_block_seconds=40,
            max_segment_count=50,
        ),
        block_policy_version="v1",
    )


def test_block_render_request_is_json_serializable():
    request = _build_request()

    payload = request.model_dump(mode="json")

    assert payload["block"]["block_text"] == "第一句。\n第二句。"
    assert payload["model_binding"]["binding_fingerprint"] == "binding-fp"
    assert payload["dirty_context"]["reuse_policy"] == "prefer_reuse"
    assert payload["adapter_options"]["gpt_sovits_local"]["noise_scale"] == 0.35
    assert payload["block_policy"]["max_segment_count"] == 50


def test_block_render_request_serializes_scope_and_join_policy_protocol():
    request = _build_request().model_copy(
        update={
            "render_scope": "segment",
            "escalated_from_scope": None,
            "requested_join_policy": "prefer_enhanced",
            "effective_join_policy": "preserve_pause",
        }
    )

    payload = request.model_dump(mode="json")

    assert payload["render_scope"] == "segment"
    assert payload["escalated_from_scope"] is None
    assert payload["requested_join_policy"] == "prefer_enhanced"
    assert payload["effective_join_policy"] == "preserve_pause"


def test_adapter_capabilities_and_reuse_policy_are_serializable():
    capabilities = AdapterCapabilities(
        block_render=True,
        exact_segment_output=True,
        segment_level_voice_binding=True,
        incremental_render=True,
        boundary_enhancement=True,
        native_join_fusion=True,
        bounded_concurrency=True,
    )

    payload = capabilities.model_dump(mode="json")

    assert payload["block_render"] is True
    assert payload["exact_segment_output"] is True
    assert payload["segment_level_voice_binding"] is True
    assert payload["incremental_render"] is True
    assert payload["bounded_concurrency"] is True


def test_block_render_result_exact_requires_precise_spans_for_all_segments():
    result = BlockRenderResult(
        block_id="block-1",
        segment_ids=["seg-1", "seg-2"],
        sample_rate=32000,
        audio=[0.1, 0.2, 0.3, 0.4, 0.5],
        audio_sample_count=5,
        segment_alignment_mode="exact",
        segment_spans=[
            SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=2, precision="exact"),
            SegmentSpan(segment_id="seg-2", sample_start=2, sample_end=5, precision="exact"),
        ],
        segment_outputs=[
            SegmentOutput(
                segment_id="seg-1",
                audio=[0.1, 0.2],
                sample_span=SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=2, precision="exact"),
                source="adapter_exact",
            )
        ],
        join_report=JoinReport(
            requested_policy="prefer_enhanced",
            applied_mode="preserve_pause",
            enhancement_applied=False,
            implementation="gpt_sovits_latent_overlap",
        ),
    )

    payload = result.model_dump(mode="json")

    assert payload["segment_alignment_mode"] == "exact"
    assert payload["segment_spans"][0]["precision"] == "exact"
    assert payload["join_report"]["implementation"] == "gpt_sovits_latent_overlap"


def test_block_render_result_rejects_missing_exact_span():
    with pytest.raises(ValidationError, match="exact"):
        BlockRenderResult(
            block_id="block-1",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=32000,
            audio=[0.1, 0.2, 0.3, 0.4, 0.5],
            audio_sample_count=5,
            segment_alignment_mode="exact",
            segment_spans=[
                SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=2, precision="exact"),
            ],
        )


def test_block_render_result_rejects_fake_block_only_spans():
    with pytest.raises(ValidationError, match="block_only"):
        BlockRenderResult(
            block_id="block-1",
            segment_ids=["seg-1"],
            sample_rate=32000,
            audio=[0.1, 0.2],
            audio_sample_count=2,
            segment_alignment_mode="block_only",
            segment_spans=[
                SegmentSpan(
                    segment_id="seg-1",
                    sample_start=0,
                    sample_end=2,
                    precision="estimated",
                    confidence=0.5,
                    source="system_estimated",
                )
            ],
        )


def test_block_adapter_error_payload_is_standardized():
    error = BlockAdapterError(
        error_code="model_required",
        message="当前请求缺少可用模型绑定。",
        details={"document_id": "doc-1"},
    )

    payload = error.to_payload().model_dump(mode="json")

    assert payload == {
        "error_code": "model_required",
        "message": "当前请求缺少可用模型绑定。",
        "details": {"document_id": "doc-1"},
    }


def test_segment_scope_unsupported_carries_reason_code_and_details():
    error = SegmentScopeUnsupported(
        reason_code="neighbor_asset_not_reusable",
        message="局部增强边界缺少可复用邻段资产。",
        details={"segment_ids": ["seg-1", "seg-2"]},
    )

    assert str(error) == "局部增强边界缺少可复用邻段资产。"
    assert error.reason_code == "neighbor_asset_not_reusable"
    assert error.scope == "segment"
    assert error.details == {"segment_ids": ["seg-1", "seg-2"]}
