from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_prepare_exit_route_returns_prepared_response(test_app_settings):
    app = create_app(settings=test_app_settings)

    with TestClient(app) as client:
        response = client.post("/v1/system/prepare-exit")

    assert response.status_code == 200
    assert response.json() == {
        "status": "prepared",
        "launcher_exit_requested": False,
        "active_render_job_status": None,
        "inference_status": "idle",
    }
