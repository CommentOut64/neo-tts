from types import SimpleNamespace

import numpy as np
import pytest
import torch

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import ReferenceContext
from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference
from backend.app.schemas.edit_session import EditableEdge, EditableSegment, InitializeEditSessionRequest


class _FakeT2SModel:
    def __init__(self, semantic_tokens: list[int]) -> None:
        self._semantic_tokens = semantic_tokens
        self.model = self

    def infer_panel(self, all_phoneme_ids, all_phoneme_len, prompt, bert, **kwargs):
        del all_phoneme_ids, all_phoneme_len, bert, kwargs
        prompt_length = prompt.shape[1]
        full = torch.tensor(
            [list(range(prompt_length)) + self._semantic_tokens],
            dtype=torch.long,
        )
        return full, len(self._semantic_tokens)


class _FakeVQModel:
    def __init__(self, *, decoder_frame_count: int, audio: np.ndarray, boundary_audio: np.ndarray) -> None:
        self.decoder_frame_count = decoder_frame_count
        self.audio = torch.tensor(audio, dtype=torch.float32).reshape(1, 1, -1)
        self.boundary_audio = torch.tensor(boundary_audio, dtype=torch.float32).reshape(1, 1, -1)
        self.decode_boundary_prefix_calls: list[dict] = []

    def decode_with_trace(self, codes, text, refer, noise_scale=0.5, speed=1, sv_emb=None):
        del text, refer, noise_scale, speed, sv_emb
        encoder_frames = torch.arange(self.decoder_frame_count, dtype=torch.float32).reshape(1, 1, -1)
        trace = {
            "encoder_frame_count": self.decoder_frame_count,
            "semantic_shape": list(codes.shape),
        }
        return self.audio.clone(), trace, encoder_frames

    def decode_boundary_prefix(
        self,
        codes,
        text,
        refer,
        *,
        left_overlap_frames,
        boundary_overlap_frame_count,
        boundary_padding_frame_count,
        boundary_result_frame_count,
        noise_scale=0.5,
        speed=1,
        sv_emb=None,
    ):
        del text, refer, noise_scale, speed, sv_emb
        self.decode_boundary_prefix_calls.append(
            {
                "codes": codes.clone(),
                "left_overlap_frames": left_overlap_frames.clone(),
                "boundary_overlap_frame_count": boundary_overlap_frame_count,
                "boundary_padding_frame_count": boundary_padding_frame_count,
                "boundary_result_frame_count": boundary_result_frame_count,
            }
        )
        trace = {
            "semantic_shape": list(codes.shape),
            "overlap_shape": list(left_overlap_frames.shape),
        }
        return self.boundary_audio.clone(), boundary_result_frame_count, trace


def _build_inference(*, decoder_frame_count: int = 14) -> GPTSoVITSOptimizedInference:
    inference = GPTSoVITSOptimizedInference.__new__(GPTSoVITSOptimizedInference)
    inference.device = "cpu"
    inference.is_half = False
    inference.hps = SimpleNamespace(
        data=SimpleNamespace(sampling_rate=32000, hop_length=640),
        model=SimpleNamespace(version="v2Pro"),
    )
    inference.t2s_model = _FakeT2SModel([101, 102, 103, 104])
    inference.vq_model = _FakeVQModel(
        decoder_frame_count=decoder_frame_count,
        audio=np.arange(decoder_frame_count * 640, dtype=np.float32),
        boundary_audio=np.arange(6 * 640, dtype=np.float32),
    )
    inference.get_phones_and_bert = lambda text, language, version, default_lang=None: (
        [11, 12, 13] if text == "参考文本。" else [21, 22],
        torch.zeros((1024, 3 if text == "参考文本。" else 2), dtype=torch.float32),
        text,
    )
    inference.get_spepc = lambda filename: (
        torch.ones((1, 704, 12), dtype=torch.float32),
        torch.ones((1, 16000), dtype=torch.float32),
    )
    inference._extract_prompt_semantic = lambda reference_audio_path: torch.tensor([7, 8, 9], dtype=torch.long)
    inference._compute_reference_speaker_embedding = (
        lambda refer_audio: torch.ones((1, 2048), dtype=torch.float32)
    )
    return inference


def test_build_reference_context_uses_request_reference_fields():
    inference = _build_inference()
    request = InitializeEditSessionRequest(
        raw_text="第一句。第二句。",
        voice_id="voice-demo",
        model_id="gpt-sovits-v2",
        reference_audio_path="ref.wav",
        reference_text="参考文本",
        reference_language="zh",
        speed=1.1,
        top_k=20,
        top_p=0.9,
        temperature=0.7,
        noise_scale=0.4,
    )

    context = inference.build_reference_context(request)

    assert isinstance(context, ReferenceContext)
    assert context.voice_id == "voice-demo"
    assert context.model_id == "gpt-sovits-v2"
    assert context.reference_text == "参考文本。"
    assert context.reference_language == "zh"
    assert context.reference_semantic_tokens.tolist() == [7, 8, 9]
    assert context.inference_config["top_k"] == 20
    assert context.inference_config["noise_scale"] == 0.4


def test_render_segment_base_shrinks_margin_when_segment_is_too_short():
    inference = _build_inference(decoder_frame_count=14)
    context = inference.build_reference_context(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="voice-demo",
            reference_audio_path="ref.wav",
            reference_text="参考文本",
            reference_language="zh",
        )
    )
    segment = EditableSegment(
        segment_id="seg-1",
        document_id="doc-1",
        order_key=1,
        raw_text="你好",
        normalized_text="你好",
        text_language="zh",
        render_version=2,
    )

    asset = inference.render_segment_base(segment, context)

    assert asset.render_version == 2
    assert asset.semantic_tokens == [101, 102, 103, 104]
    assert asset.decoder_frame_count == 14
    assert asset.left_margin_sample_count == 2 * 640
    assert asset.right_margin_sample_count == 2 * 640
    assert asset.core_sample_count == 10 * 640
    assert asset.trace is not None
    assert asset.trace["right_margin_frames"] == [12.0, 13.0]


def test_render_boundary_asset_uses_left_right_versions_as_cache_key():
    inference = _build_inference()
    context = inference.build_reference_context(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="voice-demo",
            reference_audio_path="ref.wav",
            reference_text="参考文本",
            reference_language="zh",
        )
    )
    left_asset = inference.render_segment_base(
        EditableSegment(
            segment_id="seg-left",
            document_id="doc-1",
            order_key=1,
            raw_text="左段",
            normalized_text="左段",
            text_language="zh",
            render_version=3,
        ),
        context,
    )
    right_asset = inference.render_segment_base(
        EditableSegment(
            segment_id="seg-right",
            document_id="doc-1",
            order_key=2,
            raw_text="右段",
            normalized_text="右段",
            text_language="zh",
            render_version=5,
        ),
        context,
    )
    edge = EditableEdge(
        edge_id="edge-1",
        document_id="doc-1",
        left_segment_id="seg-left",
        right_segment_id="seg-right",
        edge_version=7,
    )

    boundary_asset = inference.render_boundary_asset(left_asset, right_asset, edge, context)

    assert boundary_asset.left_render_version == 3
    assert boundary_asset.right_render_version == 5
    assert boundary_asset.edge_version == 7
    assert "seg-left" in boundary_asset.boundary_asset_id
    assert "3" in boundary_asset.boundary_asset_id
    assert "5" in boundary_asset.boundary_asset_id
    assert inference.vq_model.decode_boundary_prefix_calls[0]["boundary_result_frame_count"] == 6


def test_editable_gateway_delegates_to_backend():
    backend = SimpleNamespace(
        build_reference_context=lambda request: ("context", request.voice_id),
        render_segment_base=lambda segment, context: ("segment", segment.segment_id, context),
        render_boundary_asset=lambda left_asset, right_asset, edge, context: (
            "boundary",
            left_asset,
            right_asset,
            edge.edge_id,
            context,
        ),
    )
    gateway = EditableInferenceGateway(backend)
    segment = EditableSegment(
        segment_id="seg-1",
        document_id="doc-1",
        order_key=1,
        raw_text="你好",
        normalized_text="你好",
        text_language="zh",
    )
    edge = EditableEdge(
        edge_id="edge-1",
        document_id="doc-1",
        left_segment_id="seg-1",
        right_segment_id="seg-2",
    )

    context = gateway.build_reference_context(
        InitializeEditSessionRequest(raw_text="x", voice_id="voice-demo")
    )

    assert context == ("context", "voice-demo")
    assert gateway.render_segment_base(segment, context) == ("segment", "seg-1", context)
    assert gateway.render_boundary_asset("left", "right", edge, context) == (
        "boundary",
        "left",
        "right",
        "edge-1",
        context,
    )
