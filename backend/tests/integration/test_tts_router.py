from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app
from backend.app.services.inference_runtime import InferenceRuntimeController


def _build_settings(sample_voice_config: Path) -> AppSettings:
    project_root = sample_voice_config.parent
    return AppSettings(
        project_root=project_root,
        voices_config_path=sample_voice_config,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
    )


def test_inference_progress_endpoint_returns_snapshot(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
    runtime = InferenceRuntimeController()
    task_id = runtime.start_task(message="manual test")
    runtime.update_progress(
        task_id=task_id,
        status="inferencing",
        progress=0.75,
        message="fake progress",
        current_segment=1,
        total_segments=1,
    )
    runtime.mark_completed(task_id=task_id, result_id="result-123", message="推理完成，结果已缓存。")
    app.state.inference_runtime = runtime
    client = TestClient(app)

    response = client.get("/v1/audio/inference/progress")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["progress"] == 1.0
    assert data["result_id"] == "result-123"


def test_force_pause_endpoint_sets_cancel_flag(sample_voice_config):
    settings = _build_settings(sample_voice_config)
    app = create_app(settings=settings)
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
