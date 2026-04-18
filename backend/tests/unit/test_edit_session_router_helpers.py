from types import SimpleNamespace

import numpy as np
import torch

from backend.app.api.routers.edit_session import _build_editable_gateway
from backend.app.inference.editable_types import ReferenceContext, ResolvedRenderContext, ResolvedVoiceBinding


class _FakeBackend:
    def build_reference_context(self, resolved_context, *, progress_callback=None):
        del progress_callback
        return ReferenceContext(
            reference_context_id="ctx-demo",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=resolved_context.reference_audio_path or "demo.wav",
            reference_text=resolved_context.reference_text or "参考文本",
            reference_language=resolved_context.reference_language or "zh",
            reference_semantic_tokens=np.asarray([1, 2], dtype=np.int64),
            reference_spectrogram=torch.ones((1, 3, 3), dtype=torch.float32),
            reference_speaker_embedding=torch.ones((1, 4), dtype=torch.float32),
            inference_config_fingerprint="fp-demo",
            inference_config={},
        )

    def render_segment_base(self, segment, context, *, progress_callback=None):
        raise AssertionError("render_segment_base should not be called in this test")

    def render_boundary_asset(self, left_asset, right_asset, edge, context):
        raise AssertionError("render_boundary_asset should not be called in this test")


class _FakeModelCache:
    def __init__(self, backend):
        self._backend = backend
        self.acquired: list[tuple[str, str]] = []
        self.released: list[str] = []

    def acquire_model_handle(self, *, gpt_path: str, sovits_path: str):
        self.acquired.append((gpt_path, sovits_path))
        return SimpleNamespace(
            cache_key=f"{gpt_path}|{sovits_path}",
            engine=self._backend,
        )

    def release_model_handle(self, cache_key: str):
        self.released.append(cache_key)


def test_build_editable_gateway_reuses_app_model_cache(test_app_settings):
    backend = _FakeBackend()
    model_cache = _FakeModelCache(backend)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=test_app_settings,
                model_cache=model_cache,
            )
        )
    )

    gateway = _build_editable_gateway(request, voice_id="demo")
    context = ResolvedRenderContext(
        voice_id="demo",
        model_key="gpt-sovits-v2",
        reference_audio_path="demo.wav",
        reference_text="参考文本",
        reference_language="zh",
        resolved_voice_binding=ResolvedVoiceBinding(
            voice_binding_id="binding-demo",
            voice_id="demo",
            model_key="gpt-sovits-v2",
            gpt_path="pretrained_models/demo.ckpt",
            sovits_path="pretrained_models/demo.pth",
        ),
    )

    resolved = gateway.build_reference_context(context)

    expected_cache_key = (
        str((test_app_settings.project_root / "pretrained_models" / "demo.ckpt").resolve()),
        str((test_app_settings.project_root / "pretrained_models" / "demo.pth").resolve()),
    )
    assert model_cache.acquired == [
        (
            expected_cache_key[0],
            expected_cache_key[1],
        )
    ]
    assert model_cache.released == [f"{expected_cache_key[0]}|{expected_cache_key[1]}"]
    assert resolved.backend_cache_key == ("pretrained_models/demo.ckpt", "pretrained_models/demo.pth")
