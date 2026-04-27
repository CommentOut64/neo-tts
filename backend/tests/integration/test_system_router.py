from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app
from backend.app.api.routers import system as system_router


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


def test_file_dialog_route_returns_selected_file_path(test_app_settings, monkeypatch: pytest.MonkeyPatch):
    app = create_app(settings=test_app_settings)
    monkeypatch.setattr(
        system_router,
        "_open_file_dialog",
        lambda initial_dir=None, accept=None: "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt",
    )

    with TestClient(app) as client:
        response = client.get(
            "/v1/system/dialog/file",
            params={
                "initial_dir": "F:/GPT-SoVITS-v2pro-20250604",
                "accept": ".ckpt,.pth",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "path": "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt",
    }
