from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from backend.app.inference.editable_types import ResolvedRenderContext
from backend.app.inference.gsv_runtime_adapter import GSVRuntimeEngineAdapter
from backend.app.inference.model_cache import PyTorchModelCache
from backend.app.inference.types import InferenceCancelledError


def adapter():
    engine = GSVRuntimeEngineAdapter.__new__(GSVRuntimeEngineAdapter)
    engine._lease = SimpleNamespace(backend=SimpleNamespace(device="cpu"))
    engine._runtime = Mock()
    engine._target_device = "cpu"
    engine._target_dtype = "float32"
    engine._reference_path_resolver = lambda path: str(Path(path).resolve())
    engine._runtime.render_segment.return_value = SimpleNamespace(audio=np.ones(4, np.float32), sample_rate=10)
    return engine


def test_tts_preserves_segments_full_audio_pauses_and_single_yield(tmp_path):
    engine = adapter()
    progress = []
    output = list(engine.infer_optimized(ref_wav_path=str(tmp_path / "ref.wav"), prompt_text="hello", prompt_lang="en", text="Hello. World.", text_lang="en", pause_length=0.2, progress_callback=progress.append))
    assert len(output) == 1
    assert output[0].tolist() == [1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0]
    calls = engine._runtime.render_segment.call_args_list
    assert [call.args[1].text for call in calls] == ["Hello.", "World."]
    assert all(call.args[3].margin_frame_count == 0 for call in calls)
    assert engine._runtime.prepare_reference.call_args.args[1].text == "hello."
    assert progress[-1]["status"] == "completed"


def test_tts_cancel_before_reference_does_not_compute(tmp_path):
    engine = adapter()
    with pytest.raises(InferenceCancelledError):
        list(engine.infer_optimized(ref_wav_path=str(tmp_path / "ref.wav"), prompt_text="hello", prompt_lang="en", text="Hello.", text_lang="en", should_cancel=lambda: True))
    engine._runtime.prepare_reference.assert_not_called()


def test_tts_cancel_between_segments_does_not_publish_partial_audio(tmp_path):
    engine = adapter()
    cancelled = False

    def render(*args):
        nonlocal cancelled
        assert callable(args[4].should_cancel)
        cancelled = True
        return SimpleNamespace(audio=np.ones(4, np.float32), sample_rate=10)

    engine._runtime.render_segment.side_effect = render
    with pytest.raises(InferenceCancelledError):
        list(engine.infer_optimized(ref_wav_path=str(tmp_path / "ref.wav"), prompt_text="hello", prompt_lang="en", text="Hello. World.", text_lang="en", should_cancel=lambda: cancelled))
    assert engine._runtime.render_segment.call_count == 1


def test_cpu_target_never_promotes_to_cuda():
    engine = adapter()
    engine.ensure_on_gpu()
    engine._runtime.move_model.assert_not_called()
    assert engine.resident_device == "cpu"


@pytest.mark.parametrize("operation", ["ordinary", "editable"])
def test_managed_reference_uses_cache_roots_outside_project_cwd(tmp_path, monkeypatch, operation):
    project = tmp_path / "app"
    profile = tmp_path / "profile"
    outside = tmp_path / "outside"
    outside.mkdir()
    raw_path = "managed_voices/imported/references/ref.mp3"
    reference = profile / raw_path
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"path-resolution-fixture")
    monkeypatch.chdir(outside)
    cache = PyTorchModelCache(
        project_root=project, user_data_root=profile, managed_voices_dir=profile / "managed_voices",
        cnhubert_base_path="hubert", bert_path="bert", inference_device="cpu",
    )
    engine = adapter()
    engine._reference_path_resolver = cache._resolve_path
    engine._runtime.prepare_reference.return_value = SimpleNamespace(
        content_revision="reference", model_revision="gpt", sovits_revision="sovits", processing_revision="s1",
        payload={"semantic": [], "phones": [], "spectrogram": object(), "speaker": object(), "bert": object()},
    )
    if operation == "ordinary":
        list(engine.infer_optimized(ref_wav_path=raw_path, prompt_text="hello", prompt_lang="en", text="Hello.", text_lang="en"))
    else:
        result = engine.build_reference_context(ResolvedRenderContext(
            voice_id="imported", model_key="gsv", reference_audio_path=raw_path,
            reference_text="hello", reference_language="en",
        ))
        assert result.reference_audio_path == raw_path
    request = engine._runtime.prepare_reference.call_args.args[1]
    assert request.audio_path == str(reference.resolve())
