from __future__ import annotations

from dataclasses import replace

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


def test_version_route_returns_about_display_version(test_app_settings):
    app = create_app(
        settings=replace(
            test_app_settings,
            app_version="0.0.1-dev4",
            display_version="0.0.1",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/v1/system/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "0.0.1",
        "build_version": "0.0.1-dev4",
    }
