import io
import json
from pathlib import Path
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.inference.types import InferenceCancelledError
from backend.app.main import create_app
from backend.app.services.inference_runtime import InferenceRuntimeController
from runtime.gsv import RuntimeFailure
from runtime.gsv.errors import error_info


class FakeInferenceEngine:
    def __init__(self) -> None:
        self.last_request = None

    def synthesize_stream(self, request, *, progress_callback=None, should_cancel=None):
        self.last_request = request
        if callable(progress_callback):
            progress_callback(
                {
                    "status": "inferencing",
                    "progress": 0.75,
                    "message": "fake progress",
                    "current_segment": 1,
                    "total_segments": 1,
                }
            )
        if callable(should_cancel) and should_cancel():
            raise InferenceCancelledError("Inference cancelled by force pause request.")
        return 32000, iter([np.array([0.1, -0.1, 0.0], dtype=np.float32)])


class MissingAssetsInferenceEngine(FakeInferenceEngine):
    def synthesize_stream(self, request, *, progress_callback=None, should_cancel=None):
        raise FileNotFoundError("missing-model.ckpt")


def _build_settings(sample_voice_config: Path) -> AppSettings:
    project_root = sample_voice_config.parent
    return AppSettings(
        project_root=project_root,
        voices_config_path=sample_voice_config,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
    )


def test_audio_speech_merges_voice_defaults_and_streams_wav(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"
    assert response.headers.get("x-inference-task-id")
    result_id = response.headers.get("x-synthesis-result-id")
    assert result_id
    assert (settings.synthesis_results_dir / f"{result_id}.wav").exists()
    with wave.open(io.BytesIO(response.content), "rb") as wav_file:
        assert wav_file.getframerate() == 32000
        assert wav_file.getnframes() == 3
    assert app.state.inference_engine.last_request is not None
    assert app.state.inference_engine.last_request.request_id == response.headers["x-inference-task-id"]
    assert app.state.inference_engine.last_request.speed == 1.0
    assert app.state.inference_engine.last_request.top_k == 15
    assert app.state.inference_engine.last_request.ref_audio.endswith("demo.wav")


def test_audio_speech_returns_404_when_voice_not_found(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "missing-voice",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Voice 'missing-voice' not found."}


def test_audio_speech_rejects_unsupported_response_format(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
            "response_format": "ogg",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported response_format 'ogg'."}


def test_audio_speech_returns_422_when_inference_assets_missing(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = MissingAssetsInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("Inference assets not found:")


def test_audio_speech_accepts_multipart_custom_reference_audio(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        data={
            "input": "hello world",
            "voice": "demo",
            "ref_text": "custom reference text",
            "ref_lang": "zh",
            "speed": "0.85",
            "top_k": "9",
        },
        files={
            "ref_audio_file": ("custom.wav", b"RIFFcustom", "audio/wav"),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert app.state.inference_engine.last_request is not None
    assert app.state.inference_engine.last_request.ref_text == "custom reference text"
    assert app.state.inference_engine.last_request.ref_lang == "zh"
    assert app.state.inference_engine.last_request.speed == 0.85
    assert app.state.inference_engine.last_request.top_k == 9
    assert app.state.inference_engine.last_request.ref_audio.endswith("custom.wav")
    assert not Path(app.state.inference_engine.last_request.ref_audio).exists()


@pytest.mark.parametrize("during_iteration", [False, True])
def test_audio_speech_exposes_safe_runtime_error_and_logs_cause(sample_voice_config, during_iteration):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)

    class FailingEngine:
        def synthesize_stream(self, request, **kwargs):
            def fail():
                raise RuntimeFailure(
                    error_info("CUDA_OOM", checkpoint="semantic.generate", message="GPU memory is insufficient."),
                    RuntimeError("private-resource-path"),
                )

            if not during_iteration:
                fail()

            def stream():
                fail()
                yield  # pragma: no cover

            return 32000, stream()

    app.state.inference_engine = FailingEngine()
    response = TestClient(app).post("/v1/audio/speech", json={"input": "hello", "voice": "demo"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "CUDA_OOM"
    assert error["checkpoint"] == "semantic.generate"
    assert error["request_id"] == response.headers["x-inference-task-id"]
    assert "private-resource-path" not in response.text
    assert "Traceback" not in response.text
    state = app.state.inference_runtime.snapshot()
    assert state.status == "error"
    assert state.runtime_error == error
    logs = "\n".join(path.read_text(encoding="utf-8") for path in (settings.project_root / "logs").glob("*.log"))
    assert "private-resource-path" not in logs
    assert error["request_id"] in logs
    assert "semantic.generate" in logs
    records = [
        json.loads(line)
        for path in (settings.project_root / "logs" / "runtime-exceptions").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["error"]["request_id"] == error["request_id"]
    assert "private-resource-path" in records[0]["traceback"]
    assert records[0]["error"]["error_code"] == "CUDA_OOM"


@pytest.mark.parametrize("cancel_after_chunk", [False, True])
def test_audio_speech_closes_stream_when_consumption_finishes_or_is_cancelled(sample_voice_config, cancel_after_chunk):
    app = create_app(settings=_build_settings(sample_voice_config))
    closed = []

    class Stream:
        def __init__(self):
            self.done = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.done:
                raise StopIteration
            self.done = True
            if cancel_after_chunk:
                app.state.inference_runtime.request_force_pause(message="cancelled after chunk")
            return np.ones(8, dtype=np.float32)

        def close(self):
            closed.append(True)

    class Engine:
        def synthesize_stream(self, request, **kwargs):
            return 32000, Stream()

    app.state.inference_engine = Engine()
    response = TestClient(app).post("/v1/audio/speech", json={"input": "hello", "voice": "demo"})
    assert response.status_code == (409 if cancel_after_chunk else 200)
    assert closed == [True]


def test_audio_speech_persists_request_lifecycle_logs(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    assert response.status_code == 200
    log_files = list((settings.project_root / "logs").glob("*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "[INFO] [tts_router] 收到 TTS 请求" in content
    assert "[INFO] [tts_router] TTS 请求体解析完成" in content
    assert "[INFO] [tts_router] TTS 推理结果已缓存" in content


def test_delete_synthesis_result_endpoint(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    speech_response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )
    result_id = speech_response.headers.get("x-synthesis-result-id")
    assert result_id

    delete_response = client.delete(f"/v1/audio/results/{result_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "result_id": result_id}

    missing_response = client.delete(f"/v1/audio/results/{result_id}")
    assert missing_response.status_code == 404


def test_inference_progress_endpoint_returns_snapshot(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    response = client.get("/v1/audio/inference/progress")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["progress"] == 1.0
    assert data["result_id"] is not None


def test_force_pause_endpoint_sets_cancel_flag(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    runtime = InferenceRuntimeController()
    task_id = runtime.start_task(message="manual test")
    app.state.inference_runtime = runtime
    client = TestClient(app)

    response = client.post("/v1/audio/inference/force-pause")
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["state"]["status"] == "cancelling"
    assert runtime.should_cancel(task_id) is True


def test_cleanup_residuals_clears_temp_dirs_and_results(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    temp_ref_dir = settings.managed_voices_dir / "_temp_refs" / "dangling"
    temp_ref_dir.mkdir(parents=True, exist_ok=True)
    (temp_ref_dir / "leftover.wav").write_bytes(b"wav")
    settings.synthesis_results_dir.mkdir(parents=True, exist_ok=True)
    (settings.synthesis_results_dir / f"{'a' * 32}.wav").write_bytes(b"wav")

    response = client.post("/v1/audio/inference/cleanup-residuals")
    assert response.status_code == 200
    data = response.json()
    assert data["removed_temp_ref_dirs"] == 1
    assert data["removed_result_files"] == 1


def test_inference_params_cache_put_and_get(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    payload = {
        "voice": "demo",
        "params": {
            "speed": 0.9,
            "temperature": 1.0,
            "top_k": 12,
        },
    }
    put_response = client.put("/v1/audio/inference/params-cache", json={"payload": payload})
    assert put_response.status_code == 200
    assert put_response.json()["payload"] == payload
    assert put_response.json()["updated_at"] is not None

    get_response = client.get("/v1/audio/inference/params-cache")
    assert get_response.status_code == 200
    assert get_response.json()["payload"] == payload
