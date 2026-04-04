import time

from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.main import create_app
from backend.app.schemas.edit_session import RenderProfile, SegmentGroup, VoiceBinding
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.tests.integration.test_edit_session_router import FakeEditableInferenceBackend


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def _seed_b2_profile_binding_state(app) -> tuple[str, str]:
    repository = app.state.edit_session_repository
    active_session = repository.get_active_session()
    assert active_session is not None
    head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
    assert head_snapshot is not None
    first_segment = head_snapshot.segments[0].model_copy(deep=True)
    second_segment = head_snapshot.segments[1].model_copy(deep=True, update={"group_id": "group-1"})
    seeded_snapshot = head_snapshot.model_copy(
        deep=True,
        update={
            "segments": [first_segment, second_segment],
            "groups": [
                SegmentGroup(
                    group_id="group-1",
                    name="group-1",
                    segment_ids=[second_segment.segment_id],
                    created_by="manual",
                )
            ],
            "render_profiles": [
                RenderProfile(
                    render_profile_id="profile-session",
                    scope="session",
                    name="session",
                    speed=1.0,
                    temperature=1.0,
                )
            ],
            "voice_bindings": [
                VoiceBinding(
                    voice_binding_id="binding-session",
                    scope="session",
                    voice_id="demo",
                    model_key="gpt-sovits-v2",
                )
            ],
            "default_render_profile_id": "profile-session",
            "default_voice_binding_id": "binding-session",
        },
    )
    repository.save_snapshot(seeded_snapshot)
    return first_segment.segment_id, second_segment.segment_id


def test_profile_and_binding_patch_routes_apply_hierarchy_and_cross_model_boundary_fallback(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)

    with TestClient(app) as client:
        repository = app.state.edit_session_repository
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        first_segment_id, second_segment_id = _seed_b2_profile_binding_state(app)
        initial_timeline = client.get("/v1/edit-session/timeline")
        assert initial_timeline.status_code == 200
        initial_playable_span = tuple(initial_timeline.json()["playable_sample_span"])

        baseline_calls = len(backend.segment_calls)
        session_patch = client.patch("/v1/edit-session/session/render-profile", json={"speed": 1.25})
        assert session_patch.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)
        assert len(backend.segment_calls) - baseline_calls == 2

        group_profile_patch = client.patch("/v1/edit-session/groups/group-1/render-profile", json={"speed": 0.95})
        assert group_profile_patch.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)
        assert len(backend.segment_calls) - baseline_calls == 3

        group_binding_patch = client.patch(
            "/v1/edit-session/groups/group-1/voice-binding",
            json={"voice_id": "voice-b", "model_key": "model-b"},
        )
        assert group_binding_patch.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 4)
        assert len(backend.segment_calls) - baseline_calls == 4

        segment_profile_patch = client.patch(
            f"/v1/edit-session/segments/{second_segment_id}/render-profile",
            json={"speed": 0.75},
        )
        assert segment_profile_patch.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 5)
        assert len(backend.segment_calls) - baseline_calls == 5

        active_session = repository.get_active_session()
        assert active_session is not None
        head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert head_snapshot is not None
        resolver = RenderConfigResolver()

        first_resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=first_segment_id)
        second_resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=second_segment_id)

        assert first_resolved.render_profile.speed == 1.25
        assert second_resolved.render_profile.speed == 0.75
        assert second_resolved.voice_binding.voice_id == "voice-b"
        assert second_resolved.voice_binding.model_key == "model-b"

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        final_timeline = timeline.json()
        assert final_timeline["edge_entries"][0]["effective_boundary_strategy"] == "crossfade_only"
        assert tuple(final_timeline["playable_sample_span"]) != initial_playable_span


def test_segment_voice_binding_patch_route_rerenders_only_target_segment(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)

    with TestClient(app) as client:
        repository = app.state.edit_session_repository
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        first_segment_id, second_segment_id = _seed_b2_profile_binding_state(app)
        baseline_calls = len(backend.segment_calls)

        segment_binding_patch = client.patch(
            f"/v1/edit-session/segments/{second_segment_id}/voice-binding",
            json={"voice_id": "voice-c", "model_key": "model-c"},
        )
        assert segment_binding_patch.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)
        assert len(backend.segment_calls) - baseline_calls == 1

        active_session = repository.get_active_session()
        assert active_session is not None
        head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert head_snapshot is not None
        resolver = RenderConfigResolver()
        first_resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=first_segment_id)
        second_resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=second_segment_id)

        assert first_resolved.voice_binding.voice_id == "demo"
        assert second_resolved.voice_binding.voice_id == "voice-c"
        assert second_resolved.voice_binding.model_key == "model-c"
