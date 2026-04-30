import time

from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.main import create_app
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.edit_session import RenderProfile, SegmentGroup, VoiceBinding
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.app.services.voice_service import VoiceService
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
        assert backend.boundary_calls[-1][2] == "crossfade_only"


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


def test_configuration_commit_routes_persist_changes_without_rerender(test_app_settings):
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

        _, second_segment_id = _seed_b2_profile_binding_state(app)
        baseline_calls = len(backend.segment_calls)
        initial_timeline = client.get("/v1/edit-session/timeline")
        assert initial_timeline.status_code == 200
        initial_span = tuple(initial_timeline.json()["playable_sample_span"])

        session_profile_commit = client.patch(
            "/v1/edit-session/session/render-profile/config",
            json={"speed": 1.25, "reference_audio_path": "voices/custom.wav"},
        )
        assert session_profile_commit.status_code == 200
        assert session_profile_commit.json()["document_version"] == 2
        assert len(backend.segment_calls) == baseline_calls

        snapshot_after_session_commit = client.get("/v1/edit-session/snapshot")
        assert snapshot_after_session_commit.status_code == 200
        session_segments = snapshot_after_session_commit.json()["segments"]
        assert any(segment["render_status"] == "pending" for segment in session_segments)

        segment_binding_commit = client.patch(
            f"/v1/edit-session/segments/{second_segment_id}/voice-binding/config",
            json={"voice_id": "voice-persisted", "model_key": "model-persisted"},
        )
        assert segment_binding_commit.status_code == 200
        assert segment_binding_commit.json()["document_version"] == 3
        assert len(backend.segment_calls) == baseline_calls

        snapshot = client.get("/v1/edit-session/snapshot")
        assert snapshot.status_code == 200
        snapshot_data = snapshot.json()
        assert snapshot_data["document_version"] == 3
        assert snapshot_data["default_render_profile_id"] is not None
        assert snapshot_data["default_voice_binding_id"] is not None
        committed_segment = next(
            item for item in snapshot_data["segments"] if item["segment_id"] == second_segment_id
        )
        assert committed_segment["render_status"] == "pending"

        profiles = client.get("/v1/edit-session/render-profiles")
        assert profiles.status_code == 200

        bindings = client.get("/v1/edit-session/voice-bindings")
        assert bindings.status_code == 200
        assert any(item["voice_id"] == "voice-persisted" for item in bindings.json()["items"])

        active_session = repository.get_active_session()
        assert active_session is not None
        head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert head_snapshot is not None
        resolver = RenderConfigResolver()
        resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=second_segment_id)
        assert resolved.render_profile.reference_audio_path == "voices/custom.wav"
        assert resolved.voice_binding.voice_id == "voice-persisted"

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        timeline_data = timeline.json()
        assert timeline_data["document_version"] == 3
        assert tuple(timeline_data["playable_sample_span"]) == initial_span
        committed_timeline_segment = next(
            item for item in timeline_data["segment_entries"] if item["segment_id"] == second_segment_id
        )
        assert committed_timeline_segment["render_status"] == "pending"


def test_segment_rerender_route_consumes_pending_configuration(test_app_settings):
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

        _, second_segment_id = _seed_b2_profile_binding_state(app)
        baseline_calls = len(backend.segment_calls)

        segment_binding_commit = client.patch(
            f"/v1/edit-session/segments/{second_segment_id}/voice-binding/config",
            json={"voice_id": "voice-rerendered", "model_key": "model-rerendered"},
        )
        assert segment_binding_commit.status_code == 200
        assert len(backend.segment_calls) == baseline_calls

        rerender_response = client.post(
            f"/v1/edit-session/segments/{second_segment_id}/rerender",
        )
        assert rerender_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)
        assert len(backend.segment_calls) >= baseline_calls + 1

        active_session = repository.get_active_session()
        assert active_session is not None
        head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert head_snapshot is not None
        rerendered_segment = next(
            segment for segment in head_snapshot.segments if segment.segment_id == second_segment_id
        )
        assert rerendered_segment.render_status == "ready"
        assert rerendered_segment.render_asset_id is not None

        resolver = RenderConfigResolver()
        resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=second_segment_id)
        assert resolved.voice_binding.voice_id == "voice-rerendered"
        assert resolved.voice_binding.model_key == "model-rerendered"


def test_session_reference_override_remains_temporary_and_does_not_write_back_voice_preset(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)

    with TestClient(app) as client:
        repository = app.state.edit_session_repository
        voice_service = VoiceService(VoiceRepository(config_path=test_app_settings.voices_config_path, settings=test_app_settings))
        preset_before = voice_service.get_voice("demo")

        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        upload = client.post(
            "/v1/edit-session/reference-audio",
            files={
                "ref_audio_file": ("custom.wav", b"RIFFcustom", "audio/wav"),
            },
        )
        assert upload.status_code == 200
        uploaded = upload.json()

        patch = client.patch(
            "/v1/edit-session/session/render-profile/config",
            json={
                "reference_override": {
                    "binding_key": "demo:gpt-sovits-v2",
                    "operation": "upsert",
                    "session_reference_asset_id": uploaded["reference_asset_id"],
                    "reference_audio_path": uploaded["reference_audio_path"],
                    "reference_text": "会话临时参考",
                    "reference_language": "zh",
                }
            },
        )
        assert patch.status_code == 200

        preset_after = voice_service.get_voice("demo")
        assert preset_after.ref_audio == preset_before.ref_audio
        assert preset_after.ref_text == preset_before.ref_text
        assert preset_after.ref_lang == preset_before.ref_lang

        active_session = repository.get_active_session()
        assert active_session is not None
        head_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert head_snapshot is not None
        session_service = EditSessionService(
            repository=app.state.edit_session_repository,
            asset_store=app.state.edit_asset_store,
            runtime=app.state.edit_session_runtime,
            voice_service=voice_service,
        )
        resolver = RenderConfigResolver(voice_service=session_service)
        resolved = resolver.resolve_segment(snapshot=head_snapshot, segment_id=head_snapshot.segments[0].segment_id)

        assert resolved.resolved_reference is not None
        assert resolved.resolved_reference.reference_scope == "session_override"
        assert resolved.resolved_reference.reference_identity.endswith(uploaded["reference_asset_id"])
        assert resolved.resolved_reference.reference_audio_path == uploaded["reference_audio_path"]
        assert resolved.render_profile.reference_text == "会话临时参考"
