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
        assert test_app_settings.edit_session_db_file.exists()
        assert (test_app_settings.edit_session_assets_dir / "staging").exists()
        assert (test_app_settings.edit_session_assets_dir / "formal").exists()


def test_create_app_exposes_health_route():
    application = create_app()

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
