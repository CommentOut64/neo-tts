import threading
import time

from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.main import create_app
from backend.tests.integration.test_edit_session_router import FakeEditableInferenceBackend


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def _build_long_text(segment_count: int) -> str:
    return "".join(f"第{i}句。" for i in range(1, segment_count + 1))


def test_timeline_route_returns_markers_and_compatible_block_reuse(test_app_settings, demo_binding_ref):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": _build_long_text(51),
                "binding_ref": demo_binding_ref,
            },
        )
        assert initialize.status_code == 202
        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        initial_timeline = client.get("/v1/edit-session/timeline")
        assert initial_timeline.status_code == 200
        initial_payload = initial_timeline.json()
        snapshot_payload = client.get("/v1/edit-session/snapshot").json()
        assert initial_payload["timeline_manifest_id"]
        assert {marker["marker_type"] for marker in initial_payload["markers"]} >= {
            "segment_start",
            "segment_end",
            "edge_gap_start",
            "edge_gap_end",
            "block_start",
            "block_end",
        }
        assert [entry["order_key"] for entry in initial_payload["segment_entries"]] == sorted(
            entry["order_key"] for entry in initial_payload["segment_entries"]
        )
        assert [entry["start_sample"] for entry in initial_payload["block_entries"]] == sorted(
            entry["start_sample"] for entry in initial_payload["block_entries"]
        )
        assert {entry["segment_alignment_mode"] for entry in initial_payload["block_entries"]} == {"exact"}
        snapshot_segment_ids = {segment["segment_id"] for segment in snapshot_payload["segments"]}
        assert all(
            set(block_entry["segment_ids"]).issubset(snapshot_segment_ids)
            for block_entry in initial_payload["block_entries"]
        )

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert playback_map.json()["document_version"] == initial_payload["document_version"]
        assert playback_map.json()["composition_manifest_id"] is None

        block_audio = client.get(initial_payload["block_entries"][0]["audio_url"])
        assert block_audio.status_code == 200
        assert block_audio.headers["content-type"] == "audio/wav"

        second_block_asset_id = initial_payload["block_entries"][1]["block_asset_id"]
        first_edge_id = initial_payload["edge_entries"][0]["edge_id"]

        update_edge = client.patch(
            f"/v1/edit-session/edges/{first_edge_id}",
            json={"pause_duration_seconds": 0.8},
        )
        assert update_edge.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/timeline").json()["timeline_version"] == initial_payload["timeline_version"] + 1)

        updated_payload = client.get("/v1/edit-session/timeline").json()

        assert updated_payload["timeline_version"] == initial_payload["timeline_version"] + 1
        assert updated_payload["block_entries"][1]["block_asset_id"] == second_block_asset_id
        assert {entry["segment_alignment_mode"] for entry in updated_payload["block_entries"]} == {"exact"}


def test_timeline_route_keeps_exact_alignment_after_voice_binding_commit_and_rerender(
    test_app_settings,
    demo_binding_ref,
):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "binding_ref": demo_binding_ref,
            },
        )
        assert initialize.status_code == 202
        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        initial_snapshot = client.get("/v1/edit-session/snapshot").json()
        segment_id = initial_snapshot["segments"][0]["segment_id"]

        patch_segment = client.patch(
            f"/v1/edit-session/segments/{segment_id}",
            json={
                "text_patch": {
                    "stem": "第一句改写",
                    "terminal_raw": "。",
                    "terminal_source": "original",
                }
            },
        )
        assert patch_segment.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        commit_binding = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding/config",
            json={"binding_ref": demo_binding_ref},
        )
        assert commit_binding.status_code == 200
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        rerender = client.post(f"/v1/edit-session/segments/{segment_id}/rerender")
        assert rerender.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 4)

        timeline_payload = client.get("/v1/edit-session/timeline").json()

        assert {entry["segment_alignment_mode"] for entry in timeline_payload["block_entries"]} == {"exact"}
        assert {entry["alignment_precision"] for entry in timeline_payload["segment_entries"]} == {"exact"}
