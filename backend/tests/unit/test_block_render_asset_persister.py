from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.app.inference.block_adapter_types import (
    BlockRenderRequest,
    BlockRenderResult,
    BlockRequestBlock,
    BlockRequestSegment,
    JoinReport,
    ResolvedModelBinding,
    SegmentOutput,
    SegmentSpan,
)
from backend.app.inference.editable_types import SegmentRenderAssetPayload
from backend.app.services.block_render_asset_persister import BlockRenderAssetPersister
from backend.app.services.edit_asset_store import EditAssetStore


def _build_store(tmp_path: Path) -> EditAssetStore:
    return EditAssetStore(
        project_root=tmp_path,
        assets_dir=Path("storage/edit_session/assets"),
        export_root=Path("storage/edit_session/exports"),
        staging_ttl_seconds=60,
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
            estimated_sample_count=8,
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
            resolved_reference={"reference_id": "ref-1"},
            resolved_parameters={"speed": 1.0},
            secret_handles={},
            binding_fingerprint="binding-fp",
        ),
        block_policy_version="policy-v1",
    )


def _build_exact_result() -> BlockRenderResult:
    return BlockRenderResult(
        block_id="block-1",
        segment_ids=["seg-1", "seg-2"],
        sample_rate=4,
        audio=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        audio_sample_count=8,
        segment_alignment_mode="exact",
        segment_outputs=[
            SegmentOutput(
                segment_id="seg-1",
                sample_span=SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=3, precision="exact"),
                source="adapter_exact",
            ),
            SegmentOutput(
                segment_id="seg-2",
                sample_span=SegmentSpan(segment_id="seg-2", sample_start=3, sample_end=8, precision="exact"),
                source="adapter_exact",
            ),
        ],
        segment_spans=[
            SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=3, precision="exact"),
            SegmentSpan(segment_id="seg-2", sample_start=3, sample_end=8, precision="exact"),
        ],
        join_report=JoinReport(
            requested_policy="natural",
            applied_mode="natural",
            enhancement_applied=True,
            implementation="adapter-demo",
        ),
        diagnostics={"trace_id": "trace-1"},
    )


def _build_estimated_result() -> BlockRenderResult:
    return BlockRenderResult(
        block_id="block-1",
        segment_ids=["seg-1", "seg-2"],
        sample_rate=4,
        audio=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        audio_sample_count=6,
        segment_alignment_mode="estimated",
        segment_outputs=[
            SegmentOutput(
                segment_id="seg-1",
                sample_span=SegmentSpan(
                    segment_id="seg-1",
                    sample_start=0,
                    sample_end=2,
                    precision="estimated",
                    confidence=0.8,
                    source="system_estimated",
                ),
                confidence=0.8,
                source="system_estimated",
            ),
            SegmentOutput(
                segment_id="seg-2",
                sample_span=SegmentSpan(
                    segment_id="seg-2",
                    sample_start=2,
                    sample_end=6,
                    precision="estimated",
                    confidence=0.7,
                    source="system_estimated",
                ),
                confidence=0.7,
                source="system_estimated",
            ),
        ],
        segment_spans=[
            SegmentSpan(
                segment_id="seg-1",
                sample_start=0,
                sample_end=2,
                precision="estimated",
                confidence=0.8,
                source="system_estimated",
            ),
            SegmentSpan(
                segment_id="seg-2",
                sample_start=2,
                sample_end=6,
                precision="estimated",
                confidence=0.7,
                source="system_estimated",
            ),
        ],
    )


def _build_block_only_result() -> BlockRenderResult:
    return BlockRenderResult(
        block_id="block-1",
        segment_ids=["seg-1", "seg-2"],
        sample_rate=4,
        audio=[0.1, 0.2, 0.3, 0.4],
        audio_sample_count=4,
        segment_alignment_mode="block_only",
        segment_outputs=[
            SegmentOutput(segment_id="seg-1", source="unavailable"),
            SegmentOutput(segment_id="seg-2", source="unavailable"),
        ],
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_base_render_assets() -> dict[str, SegmentRenderAssetPayload]:
    return {
        "seg-1": SegmentRenderAssetPayload(
            render_asset_id="base-seg-1",
            segment_id="seg-1",
            render_version=1,
            sample_rate=4,
            semantic_tokens=[1, 2],
            phone_ids=[11, 12],
            decoder_frame_count=2,
            audio_sample_count=4,
            left_margin_sample_count=1,
            core_sample_count=2,
            right_margin_sample_count=1,
            left_margin_audio=np.asarray([0.01], dtype=np.float32),
            core_audio=np.asarray([0.11, 0.12], dtype=np.float32),
            right_margin_audio=np.asarray([0.13], dtype=np.float32),
            trace={"kind": "base"},
        ),
        "seg-2": SegmentRenderAssetPayload(
            render_asset_id="base-seg-2",
            segment_id="seg-2",
            render_version=1,
            sample_rate=4,
            semantic_tokens=[3, 4],
            phone_ids=[13, 14],
            decoder_frame_count=2,
            audio_sample_count=4,
            left_margin_sample_count=1,
            core_sample_count=2,
            right_margin_sample_count=1,
            left_margin_audio=np.asarray([0.21], dtype=np.float32),
            core_audio=np.asarray([0.31, 0.32], dtype=np.float32),
            right_margin_audio=np.asarray([0.33], dtype=np.float32),
            trace={"kind": "base"},
        ),
    }


def test_persister_persists_exact_block_and_segment_assets(tmp_path: Path):
    store = _build_store(tmp_path)
    persister = BlockRenderAssetPersister(asset_store=store)

    persisted = persister.persist(
        job_id="job-1",
        request=_build_request(),
        result=_build_exact_result(),
        block_render_cache_key="cache-1",
    )

    assert persisted.block_asset.block_id == "block-1"
    assert persisted.block_asset.audio_sample_count == 8
    assert [entry.segment_id for entry in persisted.timeline_block.segment_entries] == ["seg-1", "seg-2"]
    assert persisted.timeline_block.segment_entries[0].audio_sample_span == (0, 3)
    assert persisted.timeline_block.segment_entries[1].audio_sample_span == (3, 8)
    assert [(asset.asset_kind, asset.asset_id) for asset in persisted.published_assets] == [
        ("block", persisted.block_asset.block_asset_id),
        ("segment", persisted.segment_assets[0].segment_asset_id),
        ("segment", persisted.segment_assets[1].segment_asset_id),
    ]
    assert persisted.reusable_source_assets == []
    assert persisted.ephemeral_execution_assets == []

    block_dir = store.block_asset_path(persisted.block_asset.block_asset_id)
    assert (block_dir / "audio.wav").exists()
    block_metadata = _read_json(block_dir / "metadata.json")
    assert block_metadata["block_id"] == "block-1"
    assert block_metadata["adapter_id"] == "gpt_sovits_local"
    assert block_metadata["model_instance_id"] == "model-1"
    assert block_metadata["preset_id"] == "preset-1"
    assert block_metadata["model_binding_fingerprint"] == "binding-fp"
    assert block_metadata["segment_alignment_mode"] == "exact"
    assert block_metadata["block_render_cache_key"] == "cache-1"
    assert block_metadata["block_policy_version"] == "policy-v1"
    assert block_metadata["join_report"]["implementation"] == "adapter-demo"

    assert len(persisted.segment_assets) == 2
    first_segment = persisted.segment_assets[0]
    first_segment_dir = store.segment_asset_path(first_segment.segment_asset_id)
    assert (first_segment_dir / "audio.wav").exists()
    first_segment_metadata = _read_json(first_segment_dir / "metadata.json")
    assert first_segment_metadata["segment_id"] == "seg-1"
    assert first_segment_metadata["parent_block_asset_id"] == persisted.block_asset.block_asset_id
    assert first_segment_metadata["sample_span_in_block"] == [0, 3]
    assert first_segment_metadata["alignment_mode"] == "exact"
    assert first_segment_metadata["source"] == "adapter_exact"

    _, first_segment_audio = store.load_wav_asset(first_segment_dir)
    assert np.allclose(first_segment_audio, np.asarray([0.1, 0.2, 0.3], dtype=np.float32), atol=1e-4)


def test_persister_persists_reusable_base_assets_alongside_exact_formal_outputs(tmp_path: Path):
    store = _build_store(tmp_path)
    persister = BlockRenderAssetPersister(asset_store=store)
    base_render_assets = _build_base_render_assets()
    base_render_asset_ids = {
        segment_id: asset.render_asset_id for segment_id, asset in base_render_assets.items()
    }

    persisted = persister.persist(
        job_id="job-with-base-assets",
        request=_build_request(),
        result=_build_exact_result(),
        block_render_cache_key="cache-base-assets",
        base_render_asset_ids=base_render_asset_ids,
        base_render_assets=base_render_assets,
    )

    block_metadata = _read_json(store.block_asset_path(persisted.block_asset.block_asset_id) / "metadata.json")
    assert [entry["base_render_asset_id"] for entry in block_metadata["segment_entries"]] == [
        "base-seg-1",
        "base-seg-2",
    ]

    for segment_id, base_asset_id in base_render_asset_ids.items():
        base_asset_dir = store.segment_asset_path(base_asset_id)
        assert (base_asset_dir / "audio.wav").exists()
        base_metadata = _read_json(base_asset_dir / "metadata.json")
        assert base_metadata["render_asset_id"] == base_asset_id
        assert base_metadata["segment_id"] == segment_id
        assert base_metadata["core_sample_count"] == 2

    assert [asset.segment_asset_id for asset in persisted.segment_assets] != list(base_render_asset_ids.values())
    assert [(asset.segment_id, asset.render_asset_id) for asset in persisted.reusable_source_assets] == [
        ("seg-1", "base-seg-1"),
        ("seg-2", "base-seg-2"),
    ]


def test_persister_does_not_create_formal_segment_audio_for_estimated_or_block_only(tmp_path: Path):
    store = _build_store(tmp_path)
    persister = BlockRenderAssetPersister(asset_store=store)

    estimated = persister.persist(
        job_id="job-estimated",
        request=_build_request(),
        result=_build_estimated_result(),
        block_render_cache_key="cache-estimated",
    )
    block_only = persister.persist(
        job_id="job-block-only",
        request=_build_request(),
        result=_build_block_only_result(),
        block_render_cache_key="cache-block-only",
    )

    assert estimated.segment_assets == []
    assert block_only.segment_assets == []
    assert not (store.assets_root / "formal" / "segments").exists()

    estimated_metadata = _read_json(store.block_asset_path(estimated.block_asset.block_asset_id) / "metadata.json")
    assert estimated_metadata["segment_alignment_mode"] == "estimated"
    assert estimated_metadata["segment_spans"][0]["precision"] == "estimated"
    assert all(entry["render_asset_id"] is None for entry in estimated_metadata["segment_entries"])

    block_only_metadata = _read_json(store.block_asset_path(block_only.block_asset.block_asset_id) / "metadata.json")
    assert block_only_metadata["segment_alignment_mode"] == "block_only"
    assert block_only_metadata["segment_spans"] == []
    assert block_only.timeline_block.segment_entries == []


def test_persister_keeps_formal_state_clean_when_validation_or_terminal_status_blocks_commit(tmp_path: Path):
    store = _build_store(tmp_path)
    persister = BlockRenderAssetPersister(asset_store=store)
    invalid_result = _build_exact_result().model_copy(
        update={
            "segment_spans": [
                SegmentSpan(segment_id="seg-1", sample_start=0, sample_end=3, precision="exact"),
                SegmentSpan(segment_id="seg-2", sample_start=3, sample_end=9, precision="exact"),
            ]
        }
    )

    with pytest.raises(ValueError):
        persister.persist(
            job_id="job-invalid",
            request=_build_request(),
            result=invalid_result,
            block_render_cache_key="cache-invalid",
        )

    skipped = persister.persist(
        job_id="job-cancelled",
        request=_build_request(),
        result=_build_exact_result(),
        block_render_cache_key="cache-cancelled",
        terminal_status="cancelled",
    )

    assert skipped is None
    assert not (store.assets_root / "formal" / "blocks").exists()
    assert not (store.assets_root / "formal" / "segments").exists()
    assert not (store.assets_root / "staging" / "job-invalid").exists()
    assert not (store.assets_root / "staging" / "job-cancelled").exists()


def test_persister_writes_required_block_and_segment_metadata_fields(tmp_path: Path):
    store = _build_store(tmp_path)
    persister = BlockRenderAssetPersister(asset_store=store)

    persisted = persister.persist(
        job_id="job-meta",
        request=_build_request(),
        result=_build_exact_result(),
        block_render_cache_key="cache-meta",
    )

    block_metadata = _read_json(store.block_asset_path(persisted.block_asset.block_asset_id) / "metadata.json")
    assert set(block_metadata) >= {
        "block_id",
        "block_asset_id",
        "adapter_id",
        "model_instance_id",
        "preset_id",
        "model_binding_fingerprint",
        "segment_alignment_mode",
        "segment_spans",
        "join_report",
        "block_render_cache_key",
        "block_policy_version",
    }

    segment_metadata = _read_json(store.segment_asset_path(persisted.segment_assets[0].segment_asset_id) / "metadata.json")
    assert set(segment_metadata) >= {
        "segment_asset_id",
        "segment_id",
        "parent_block_asset_id",
        "model_instance_id",
        "preset_id",
        "model_binding_fingerprint",
        "sample_span_in_block",
        "source",
        "alignment_mode",
    }
