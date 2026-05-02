import io
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.text.segment_standardizer import build_segment_display_text


def _wait_for_terminal_job(client: TestClient, job_id: str, *, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    last_payload: dict | None = None
    while time.time() < deadline:
        response = client.get(f"/v1/edit-session/render-jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "cancelled_partial", "failed"}:
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


def _segment_display_text(segment: dict) -> str:
    return build_segment_display_text(
        stem=segment["stem"],
        text_language=segment["text_language"],
        terminal_raw=segment.get("terminal_raw", ""),
        terminal_closer_suffix=segment.get("terminal_closer_suffix", ""),
        terminal_source=segment.get("terminal_source", "synthetic"),
    )


def _build_text_patch(display_text: str) -> dict:
    if display_text.endswith("。"):
        return {
            "stem": display_text[:-1],
            "terminal_raw": "。",
            "terminal_source": "original",
        }
    return {"stem": display_text}


def _assert_frontend_consumable_state(client: TestClient, expected_segments: list[str]) -> None:
    snapshot = client.get("/v1/edit-session/snapshot")
    assert snapshot.status_code == 200, snapshot.text
    snapshot_payload = snapshot.json()
    assert snapshot_payload["session_status"] == "ready"

    segments = _fetch_paginated_items(client, "/v1/edit-session/segments", limit=2)
    edges = _fetch_paginated_items(client, "/v1/edit-session/edges", limit=2)
    assert [_segment_display_text(item) for item in segments] == expected_segments
    assert len(edges) == max(0, len(expected_segments) - 1)

    timeline = client.get("/v1/edit-session/timeline")
    assert timeline.status_code == 200, timeline.text
    timeline_payload = timeline.json()
    assert len(timeline_payload["block_entries"]) >= 1
    assert {entry["segment_alignment_mode"] for entry in timeline_payload["block_entries"]} == {"exact"}
    assert len(timeline_payload["segment_entries"]) == len(expected_segments)
    assert {entry["alignment_precision"] for entry in timeline_payload["segment_entries"]} == {"exact"}

    playback_map = client.get("/v1/edit-session/playback-map")
    assert playback_map.status_code == 200, playback_map.text
    playback_payload = playback_map.json()
    assert len(playback_payload["entries"]) == len(expected_segments)
    spans = [tuple(entry["audio_sample_span"]) for entry in playback_payload["entries"]]
    assert spans == sorted(spans)
    assert all(start < end for start, end in spans)

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


def test_real_model_edit_session_flow(real_model_env, real_model_app_settings):
    exports_root = real_model_app_settings.edit_session_exports_dir
    updated_expected_segments = [
        real_model_env.updated_first_segment_text,
        *real_model_env.expected_segments[1:],
    ]
    appended_segment_text = "这是新增的一句。"
    appended_expected_segments = [*updated_expected_segments, appended_segment_text]
    app = create_app(settings=real_model_app_settings)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": real_model_env.tts_text,
                "text_language": real_model_env.text_language,
                "binding_ref": real_model_env.binding_ref,
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
        baseline_text = _segment_display_text(initial_snapshot["segments"][0])
        baseline_pause = initial_snapshot["edges"][0]["pause_duration_seconds"]
        baseline_strategy = initial_snapshot["edges"][0]["boundary_strategy"]
        assert [_segment_display_text(item) for item in initial_snapshot["segments"]] == real_model_env.expected_segments
        _assert_frontend_consumable_state(client, real_model_env.expected_segments)

        patch_segment = client.patch(
            f"/v1/edit-session/segments/{segment_id}",
            json={
                "text_patch": _build_text_patch(real_model_env.updated_first_segment_text),
                "text_language": real_model_env.text_language,
            },
        )
        assert patch_segment.status_code == 202, patch_segment.text
        _wait_for_terminal_job(client, patch_segment.json()["job"]["job_id"])

        updated_snapshot = _wait_for_snapshot_version(client, 2)
        assert _segment_display_text(updated_snapshot["segments"][0]) == real_model_env.updated_first_segment_text
        assert [_segment_display_text(item) for item in updated_snapshot["segments"]] == updated_expected_segments

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
        previous_voice_binding_id = pause_snapshot["segments"][0]["voice_binding_id"]

        voice_binding_commit = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding/config",
            json={
                "binding_ref": real_model_env.binding_ref,
                "speaker_meta": {"e2e_scope": "segment_voice_binding"},
            },
        )
        assert voice_binding_commit.status_code == 200, voice_binding_commit.text
        committed_snapshot = _wait_for_snapshot_version(client, 4)
        assert committed_snapshot["segments"][0]["voice_binding_id"] != previous_voice_binding_id
        assert committed_snapshot["segments"][0]["render_status"] == "ready"

        rerender = client.post(f"/v1/edit-session/segments/{segment_id}/rerender")
        assert rerender.status_code == 202, rerender.text
        _wait_for_terminal_job(client, rerender.json()["job"]["job_id"])

        rerendered_snapshot = _wait_for_snapshot_version(client, 5)
        assert _segment_display_text(rerendered_snapshot["segments"][0]) == real_model_env.updated_first_segment_text
        assert rerendered_snapshot["edges"][0]["pause_duration_seconds"] == 0.8
        _assert_frontend_consumable_state(client, updated_expected_segments)

        timeline_before_strategy = client.get("/v1/edit-session/timeline")
        assert timeline_before_strategy.status_code == 200, timeline_before_strategy.text
        current_block_id = timeline_before_strategy.json()["block_entries"][0]["block_asset_id"]

        edge_preview = client.get("/v1/edit-session/preview", params={"edge_id": edge_id})
        assert edge_preview.status_code == 200, edge_preview.text
        assert edge_preview.json()["preview_kind"] == "edge"

        block_preview = client.get("/v1/edit-session/preview", params={"block_id": current_block_id})
        assert block_preview.status_code == 200, block_preview.text
        assert block_preview.json()["preview_kind"] == "block"

        patch_strategy = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"boundary_strategy": "crossfade_only"},
        )
        assert patch_strategy.status_code == 202, patch_strategy.text
        _wait_for_terminal_job(client, patch_strategy.json()["job"]["job_id"])

        strategy_snapshot = _wait_for_snapshot_version(client, 6)
        assert strategy_snapshot["edges"][0]["boundary_strategy"] == "crossfade_only"
        assert strategy_snapshot["edges"][0]["pause_duration_seconds"] == 0.8

        append = client.post(
            "/v1/edit-session/append",
            json={
                "raw_text": appended_segment_text,
                "text_language": real_model_env.text_language,
            },
        )
        assert append.status_code == 202, append.text
        _wait_for_terminal_job(client, append.json()["job"]["job_id"])

        appended_snapshot = _wait_for_snapshot_version(client, 7)
        assert [_segment_display_text(item) for item in appended_snapshot["segments"]] == appended_expected_segments
        _assert_frontend_consumable_state(client, appended_expected_segments)

        segment_export_root = exports_root / "e2e-segments"
        create_segment_export = client.post(
            "/v1/edit-session/exports/segments",
            json={
                "document_version": appended_snapshot["document_version"],
                "target_dir": str(segment_export_root),
                "overwrite_policy": "replace",
            },
        )
        assert create_segment_export.status_code == 202, create_segment_export.text
        segment_export_job = _wait_for_export_job(client, create_segment_export.json()["job"]["export_job_id"])
        assert segment_export_job["output_manifest"]["export_kind"] == "segments"
        assert len(segment_export_job["output_manifest"]["segment_files"]) == len(appended_expected_segments)

        restore = client.post("/v1/edit-session/restore-baseline")
        assert restore.status_code == 202, restore.text
        _wait_for_terminal_job(client, restore.json()["job"]["job_id"])

        restored_snapshot = _wait_for_snapshot_version(client, 8)
        assert [_segment_display_text(item) for item in restored_snapshot["segments"]] == real_model_env.expected_segments
        assert restored_snapshot["edges"][0]["pause_duration_seconds"] == baseline_pause
        assert restored_snapshot["edges"][0]["boundary_strategy"] == baseline_strategy

        block_export_root = exports_root / "e2e-blocks"
        create_block_export = client.post(
            "/v1/edit-session/exports",
            json={
                "document_version": restored_snapshot["document_version"],
                "target_dir": str(block_export_root),
                "audio": {"kind": "blocks", "overwrite_policy": "replace"},
            },
        )
        assert create_block_export.status_code == 202, create_block_export.text
        block_export_job = _wait_for_export_job(client, create_block_export.json()["job"]["export_job_id"])
        assert block_export_job["output_manifest"]["export_kind"] == "blocks"
        assert len(block_export_job["output_manifest"]["block_files"]) >= 1
        assert all(
            entry["segment_alignment_mode"] == "exact"
            for entry in block_export_job["output_manifest"]["block_manifest_entries"]
        )

        composition_export_root = exports_root / "e2e-composition"
        create_composition_export = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": restored_snapshot["document_version"],
                "target_dir": str(composition_export_root),
                "overwrite_policy": "replace",
            },
        )
        assert create_composition_export.status_code == 202, create_composition_export.text
        composition_export_job = _wait_for_export_job(
            client,
            create_composition_export.json()["job"]["export_job_id"],
        )
        composition_path = Path(composition_export_job["output_manifest"]["composition_file"])
        assert composition_path.exists()

        composition = client.get("/v1/edit-session/composition")
        assert composition.status_code == 200, composition.text
        composition_payload = composition.json()
        composition_audio = client.get(composition_payload["audio_delivery"]["audio_url"])
        assert composition_audio.status_code == 200, composition_audio.text
        total_sample_count = _read_wav_sample_count(composition_audio.content)
        timeline_payload = client.get("/v1/edit-session/timeline").json()
        assert total_sample_count == timeline_payload["playable_sample_span"][1]
        assert baseline_text == real_model_env.expected_segments[0]
