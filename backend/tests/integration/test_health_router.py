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


def test_create_app_exposes_health_route():
    application = create_app()

    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
