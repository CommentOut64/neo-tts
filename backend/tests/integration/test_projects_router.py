from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services.project_store import sha256_bytes


def _payload(project_id: str = "p1") -> dict:
    blob = b"router-audio"
    digest = sha256_bytes(blob)
    return {
        "project": {"project_id": project_id, "workspace_id": "w1", "head_snapshot_id": "s1"},
        "blobs": [{"sha256": digest, "data": blob.decode()}],
        "assets": [{"asset_id": "a1", "kind": "formal", "blob_sha256": digest, "byte_count": len(blob), "ready": 1}],
        "snapshots": [{"snapshot_id": "s1", "kind": "head", "segments": [{"segment_id": "seg1", "text": {"value": "hello"}}]}],
        "references": [],
        "asset_refs": [{"owner_type": "snapshot", "owner_id": "s1", "asset_id": "a1", "purpose": "formal"}],
    }


def test_project_router_new_save_state(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        created = client.post("/v1/projects/new", json={"project_id": "p1", "workspace_id": "w1"})
        assert created.status_code == 201
        assert created.json()["project_id"] == "p1"
        saved = client.post("/v1/projects/save", json={"payload": _payload()})
        assert saved.status_code == 200
        assert saved.json()["save_revision"] == 1
        state = client.get("/v1/projects/state")
        assert state.status_code == 200
        assert state.json()["dirty"] is False


def test_project_router_first_save_initializes_workspace(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        saved = client.post("/v1/projects/save", json={"payload": _payload()})

        assert saved.status_code == 200
        assert saved.json()["save_revision"] == 1
        assert saved.json()["project_id"] == "p1"
        assert saved.json()["workspace_id"]


def test_project_router_first_save_as_initializes_workspace(test_app_settings, tmp_path):
    application = create_app(settings=test_app_settings)
    target = tmp_path / "p1-copy.neo"
    with TestClient(application) as client:
        saved = client.post(
            "/v1/projects/save-as",
            json={"payload": _payload(), "target": str(target)},
        )

        assert saved.status_code == 200
        assert saved.json()["save_revision"] == 0
        assert target.is_file()


def test_project_router_invalid_first_save_returns_validation_error(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        response = client.post("/v1/projects/save", json={"payload": {}})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PROJECT_INVALID_REQUEST"
        assert response.json()["workspace_id"] is None


def test_project_router_missing_required_fields_returns_stable_error_envelope(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        created = client.post("/v1/projects/new", json={"project_id": "p1", "workspace_id": "w1"})
        assert created.status_code == 201

        response = client.post("/v1/projects/open", json={})

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == body["detail"]
    assert body["error"]["code"] == "PROJECT_INVALID_REQUEST"
    assert body["error"]["phase"] == "validation"
    assert body["error"]["retryable"] is False
    assert body["error"]["action"] == "fix_request"
    assert body["error"]["request_id"]


def test_project_router_invalid_capture_token_does_not_return_500(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        client.post("/v1/projects/new", json={"project_id": "p1", "workspace_id": "w1"})
        response = client.post(
            "/v1/projects/save",
            json={"payload": _payload(), "token": {"workspace_id": "w1"}},
            headers={"X-Request-ID": "test-project-request"},
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "PROJECT_INVALID_REQUEST"
    assert error["request_id"] == "test-project-request"


def test_project_router_nonzero_token_on_first_save_is_write_busy_not_storage_error(test_app_settings):
    application = create_app(settings=test_app_settings)
    with TestClient(application) as client:
        response = client.post(
            "/v1/projects/save",
            json={
                "payload": _payload(),
                "token": {
                    "workspace_id": "stale-workspace",
                    "project_id": "p1",
                    "expected_save_revision": 3,
                },
            },
        )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "NEO_WRITE_BUSY"
    assert error["retryable"] is True
    assert error["action"] == "retry"
