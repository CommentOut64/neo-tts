from dataclasses import replace

from fastapi.testclient import TestClient

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
