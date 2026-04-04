import io
import time
import wave

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.inference.editable_types import build_boundary_asset_id


def _wait_for_terminal_job(client: TestClient, job_id: str, *, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        response = client.get(f"/v1/edit-session/render-jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "cancelled", "failed"}:
            assert payload["status"] == "completed", payload
            return payload
        time.sleep(0.25)
    raise AssertionError(f"Render job '{job_id}' 未在 {timeout:.1f}s 内进入终态: {last_payload}")


def _wait_for_snapshot_version(client: TestClient, version: int, *, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        response = client.get("/v1/edit-session/snapshot")
        assert response.status_code == 200, response.text
        payload = response.json()
        last_payload = payload
        if payload["session_status"] == "ready" and payload["document_version"] == version:
            return payload
        time.sleep(0.25)
    raise AssertionError(f"snapshot 未在 {timeout:.1f}s 内到达 document_version={version}: {last_payload}")


def _wait_for_export_job(client: TestClient, export_job_id: str, *, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        response = client.get(f"/v1/edit-session/exports/{export_job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "failed"}:
            assert payload["status"] == "completed", payload
            return payload
        time.sleep(0.25)
    raise AssertionError(f"export job '{export_job_id}' 未在 {timeout:.1f}s 内进入终态: {last_payload}")


def _read_wav_sample_count(payload: bytes) -> int:
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        return wav_file.getnframes()


def _fetch_paginated_items(client: TestClient, path: str, *, limit: int = 2) -> list[dict]:
    items: list[dict] = []
    cursor = None
    while True:
        params = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        payload = response.json()
        items.extend(payload["items"])
        cursor = payload["next_cursor"]
        if cursor is None:
            return items


def _assert_frontend_consumable_state(client: TestClient, expected_segments: list[str]) -> None:
    snapshot = client.get("/v1/edit-session/snapshot")
    assert snapshot.status_code == 200, snapshot.text
    snapshot_payload = snapshot.json()
    assert snapshot_payload["session_status"] == "ready"

    segments = _fetch_paginated_items(client, "/v1/edit-session/segments", limit=2)
    edges = _fetch_paginated_items(client, "/v1/edit-session/edges", limit=2)
    assert [item["raw_text"] for item in segments] == expected_segments
    assert len(edges) == max(0, len(expected_segments) - 1)

    playback_map = client.get("/v1/edit-session/playback-map")
    assert playback_map.status_code == 200, playback_map.text
    playback_payload = playback_map.json()
    assert len(playback_payload["entries"]) == len(expected_segments)
    spans = [tuple(entry["audio_sample_span"]) for entry in playback_payload["entries"]]
    assert spans == sorted(spans)
    assert all(start < end for start, end in spans)

    composition = client.get("/v1/edit-session/composition")
    if composition.status_code == 404:
        export_response = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": snapshot_payload["document_version"],
                "target_dir": f"e2e-composition-v{snapshot_payload['document_version']}",
                "overwrite_policy": "replace",
            },
        )
        assert export_response.status_code == 202, export_response.text
        _wait_for_export_job(client, export_response.json()["job"]["export_job_id"])
        composition = client.get("/v1/edit-session/composition")
    assert composition.status_code == 200, composition.text
    composition_payload = composition.json()
    composition_audio = client.get(composition_payload["audio_delivery"]["audio_url"])
    assert composition_audio.status_code == 200, composition_audio.text
    total_sample_count = _read_wav_sample_count(composition_audio.content)
    assert total_sample_count == playback_payload["playable_sample_span"][1]
    assert len(composition_audio.content) == composition_payload["audio_delivery"]["byte_length"]

    segment_by_id = {item["segment_id"]: item for item in segments}
    for entry in playback_payload["entries"]:
        segment = segment_by_id[entry["segment_id"]]
        metadata = client.get(f"/v1/edit-session/assets/segments/{segment['render_asset_id']}")
        assert metadata.status_code == 200, metadata.text
        audio = client.get(metadata.json()["audio_delivery"]["audio_url"])
        assert audio.status_code == 200, audio.text
        sample_count = _read_wav_sample_count(audio.content)
        span_start, span_end = entry["audio_sample_span"]
        assert sample_count >= span_end - span_start

    for edge in edges:
        left_segment = segment_by_id[edge["left_segment_id"]]
        right_segment = segment_by_id[edge["right_segment_id"]]
        boundary_asset_id = build_boundary_asset_id(
            left_segment_id=edge["left_segment_id"],
            left_render_version=left_segment["render_version"],
            right_segment_id=edge["right_segment_id"],
            right_render_version=right_segment["render_version"],
            edge_version=edge["edge_version"],
            boundary_strategy=edge["boundary_strategy"],
        )
        metadata = client.get(f"/v1/edit-session/assets/boundaries/{boundary_asset_id}")
        assert metadata.status_code == 200, metadata.text
        audio = client.get(metadata.json()["audio_delivery"]["audio_url"])
        assert audio.status_code == 200, audio.text
        assert _read_wav_sample_count(audio.content) > 0


def test_real_model_edit_session_flow(real_model_env, real_model_app_settings):
    app = create_app(settings=real_model_app_settings)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": real_model_env.tts_text,
                "text_language": real_model_env.text_language,
                "voice_id": real_model_env.voice_id,
                "segment_boundary_mode": real_model_env.segment_boundary_mode,
            },
        )
        assert initialize.status_code == 202, initialize.text
        initialize_job_id = initialize.json()["job"]["job_id"]
        _wait_for_terminal_job(client, initialize_job_id)

        initial_snapshot = _wait_for_snapshot_version(client, 1)
        assert initial_snapshot["session_status"] == "ready"
        assert len(initial_snapshot["segments"]) == len(real_model_env.expected_segments)
        assert len(initial_snapshot["edges"]) == len(real_model_env.expected_segments) - 1
        segment_id = initial_snapshot["segments"][0]["segment_id"]
        edge_id = initial_snapshot["edges"][0]["edge_id"]
        baseline_text = initial_snapshot["segments"][0]["raw_text"]
        baseline_pause = initial_snapshot["edges"][0]["pause_duration_seconds"]
        baseline_strategy = initial_snapshot["edges"][0]["boundary_strategy"]
        assert [item["raw_text"] for item in initial_snapshot["segments"]] == real_model_env.expected_segments
        _assert_frontend_consumable_state(client, real_model_env.expected_segments)

        patch_segment = client.patch(
            f"/v1/edit-session/segments/{segment_id}",
            json={
                "raw_text": real_model_env.updated_first_segment_text,
                "text_language": real_model_env.text_language,
            },
        )
        assert patch_segment.status_code == 202, patch_segment.text
        _wait_for_terminal_job(client, patch_segment.json()["job"]["job_id"])

        updated_snapshot = _wait_for_snapshot_version(client, 2)
        assert updated_snapshot["segments"][0]["raw_text"] == real_model_env.updated_first_segment_text

        preview = client.get("/v1/edit-session/preview", params={"segment_id": segment_id})
        assert preview.status_code == 200, preview.text
        assert preview.json()["preview_kind"] == "segment"

        patch_pause_only = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"pause_duration_seconds": 0.8},
        )
        assert patch_pause_only.status_code == 202, patch_pause_only.text
        _wait_for_terminal_job(client, patch_pause_only.json()["job"]["job_id"])

        pause_snapshot = _wait_for_snapshot_version(client, 3)
        assert pause_snapshot["edges"][0]["pause_duration_seconds"] == 0.8
        assert pause_snapshot["edges"][0]["boundary_strategy"] == baseline_strategy

        patch_strategy = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"boundary_strategy": "crossfade_only"},
        )
        assert patch_strategy.status_code == 202, patch_strategy.text
        _wait_for_terminal_job(client, patch_strategy.json()["job"]["job_id"])

        strategy_snapshot = _wait_for_snapshot_version(client, 4)
        assert strategy_snapshot["edges"][0]["boundary_strategy"] == "crossfade_only"
        assert strategy_snapshot["edges"][0]["pause_duration_seconds"] == 0.8

        restore = client.post("/v1/edit-session/restore-baseline")
        assert restore.status_code == 202, restore.text
        _wait_for_terminal_job(client, restore.json()["job"]["job_id"])

        restored_snapshot = _wait_for_snapshot_version(client, 5)
        assert restored_snapshot["segments"][0]["raw_text"] == baseline_text
        assert restored_snapshot["edges"][0]["pause_duration_seconds"] == baseline_pause
        assert restored_snapshot["edges"][0]["boundary_strategy"] == baseline_strategy
        _assert_frontend_consumable_state(client, real_model_env.expected_segments)
