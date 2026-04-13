from dataclasses import replace
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import app, create_app


def test_health_endpoint_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_app_lifespan_initializes_inference_dependencies():
    with TestClient(app) as client:
        assert hasattr(client.app.state, "model_cache")
        assert hasattr(client.app.state, "inference_engine")


def test_app_lifespan_initializes_edit_session_dependencies(test_app_settings):
    application = create_app(settings=test_app_settings)

    with TestClient(application) as client:
        assert hasattr(client.app.state, "edit_session_repository")
        assert hasattr(client.app.state, "edit_asset_store")
        assert hasattr(client.app.state, "edit_session_runtime")
        assert hasattr(client.app.state, "edit_session_maintenance_service")
        assert hasattr(client.app.state, "edit_session_cleanup_task")
        assert test_app_settings.edit_session_db_file.exists()
        assert (test_app_settings.edit_session_assets_dir / "staging").exists()
        assert (test_app_settings.edit_session_assets_dir / "formal").exists()


def test_app_lifespan_preloads_configured_voices_on_start(test_app_settings, monkeypatch):
    preload_calls: list[tuple[str, str]] = []

    class _FakeModelCache:
        def __init__(self, project_root, cnhubert_base_path, bert_path, engine_factory=None, warmup_hook=None) -> None:
            del project_root, cnhubert_base_path, bert_path, engine_factory, warmup_hook

        def get_engine(self, gpt_path, sovits_path):
            preload_calls.append((gpt_path, sovits_path))
            return object()

        def clear(self):
            return None

    monkeypatch.setattr(
        "backend.app.inference.model_cache.PyTorchModelCache",
        _FakeModelCache,
    )
    application = create_app(settings=replace(test_app_settings, preload_on_start=True, preload_voice_ids=("demo",)))

    with TestClient(application):
        assert preload_calls == [
            (
                str((test_app_settings.project_root / "pretrained_models" / "demo.ckpt").resolve()),
                str((test_app_settings.project_root / "pretrained_models" / "demo.pth").resolve()),
            )
        ]


def test_create_app_exposes_health_route():
    application = create_app()

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_lifespan_offloads_idle_models_under_gpu_pressure_before_loading_new_model(tmp_path, monkeypatch):
    class _FakeEngine:
        def __init__(self, name: str, offload_counter: dict[str, int]) -> None:
            self.name = name
            self.resident_device = "cuda"
            self.offload_calls = 0
            self.ensure_calls = 0
            self._offload_counter = offload_counter

        def offload_from_gpu(self) -> None:
            self.offload_calls += 1
            self.resident_device = "cpu"
            self._offload_counter["count"] += 1

        def ensure_on_gpu(self) -> None:
            self.ensure_calls += 1
            self.resident_device = "cuda"

    project_root = tmp_path
    voices_config_path = project_root / "voices.json"
    voices_config_path.write_text(
        json.dumps(
            {
                "neuro2": {
                    "gpt_path": "pretrained_models/neuro2.ckpt",
                    "sovits_path": "pretrained_models/neuro2.pth",
                    "ref_audio": "pretrained_models/neuro2.wav",
                    "ref_text": "ref",
                    "ref_lang": "zh",
                    "description": "default voice",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=project_root,
        voices_config_path=voices_config_path,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
        edit_session_db_file=project_root / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=project_root / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=project_root / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
        preload_on_start=True,
        preload_voice_ids=("neuro2",),
        gpu_offload_enabled=True,
        gpu_min_free_mb=2048,
        gpu_reserve_mb_for_load=4096,
    )
    offload_counter = {"count": 0}
    free_bytes_state = {"value": 6 * 1024 * 1024 * 1024}

    def fake_build_engine(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        del sovits_path, cnhubert_path, bert_path
        return _FakeEngine(Path(gpt_path).stem, offload_counter)

    def fake_mem_get_info():
        if offload_counter["count"] > 0:
            return (5 * 1024 * 1024 * 1024, 8 * 1024 * 1024 * 1024)
        return (free_bytes_state["value"], 8 * 1024 * 1024 * 1024)

    monkeypatch.setattr(
        "backend.app.inference.model_cache.PyTorchModelCache._build_engine",
        staticmethod(fake_build_engine),
    )
    monkeypatch.setattr(
        "backend.app.inference.model_cache.PyTorchModelCache._default_cuda_mem_get_info",
        staticmethod(lambda: fake_mem_get_info),
    )
    application = create_app(settings=settings)

    with TestClient(application) as client:
        model_cache = client.app.state.model_cache

        neuro2_handle = model_cache.get_model_handle("pretrained_models/neuro2.ckpt", "pretrained_models/neuro2.pth")
        idle_handle_a = model_cache.acquire_model_handle("pretrained_models/a.ckpt", "pretrained_models/a.pth")
        model_cache.release_model_handle(idle_handle_a.cache_key)
        idle_handle_b = model_cache.acquire_model_handle("pretrained_models/b.ckpt", "pretrained_models/b.pth")
        model_cache.release_model_handle(idle_handle_b.cache_key)
        active_handle_c = model_cache.acquire_model_handle("pretrained_models/c.ckpt", "pretrained_models/c.pth")

        free_bytes_state["value"] = 1024 * 1024 * 1024
        new_handle_d = model_cache.acquire_model_handle("pretrained_models/d.ckpt", "pretrained_models/d.pth")

        assert neuro2_handle.pinned is True
        assert neuro2_handle.resident_device == "cuda"
        assert idle_handle_a.resident_device == "cpu"
        assert idle_handle_a.engine.offload_calls == 1
        assert idle_handle_b.resident_device == "cuda"
        assert active_handle_c.resident_device == "cuda"
        assert active_handle_c.active_count == 1
        assert new_handle_d.resident_device == "cuda"
        assert new_handle_d.active_count == 1

        model_cache.release_model_handle(active_handle_c.cache_key)
        model_cache.release_model_handle(new_handle_d.cache_key)
