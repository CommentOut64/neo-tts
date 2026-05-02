import time

from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.main import create_app
from backend.app.schemas.edit_session import RenderProfile, SegmentGroup, VoiceBinding
from backend.app.text.segment_standardizer import build_segment_display_text
from backend.tests.integration.test_edit_session_router import FakeEditableInferenceBackend


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def _segment_display_text(segment) -> str:
    return build_segment_display_text(
        stem=segment.stem,
        text_language=segment.text_language,
        terminal_raw=segment.terminal_raw,
        terminal_closer_suffix=segment.terminal_closer_suffix,
        terminal_source=segment.terminal_source,
    )


def test_append_creates_new_tail_segments_and_auto_group(test_app_settings, demo_binding_ref):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)

    with TestClient(app) as client:
        repository = app.state.edit_session_repository
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "binding_ref": demo_binding_ref,
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        active_session = repository.get_active_session()
        assert active_session is not None
        before_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert before_snapshot is not None
        before_render_asset_ids = [segment.render_asset_id for segment in before_snapshot.segments]
        before_call_count = len(backend.segment_calls)

        append_response = client.post(
            "/v1/edit-session/append",
            json={
                "raw_text": "第三句。第四句。",
                "group_render_profile": {
                    "speed": 1.15,
                    "temperature": 0.85,
                },
                "group_voice_binding": {
                    "binding_ref": demo_binding_ref,
                },
            },
        )

        assert append_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        active_session = repository.get_active_session()
        assert active_session is not None
        after_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert after_snapshot is not None

        assert after_snapshot.document_id == before_snapshot.document_id
        assert after_snapshot.document_version == 2
        assert [_segment_display_text(segment) for segment in after_snapshot.segments] == [
            "第一句。",
            "第二句。",
            "第三句。",
            "第四句。",
        ]
        assert [segment.render_asset_id for segment in after_snapshot.segments[:2]] == before_render_asset_ids
        assert len(backend.segment_calls) - before_call_count == 2

        new_group_ids = {segment.group_id for segment in after_snapshot.segments[2:]}
        assert len(new_group_ids) == 1
        assert None not in new_group_ids
        group_id = next(iter(new_group_ids))
        group = next(item for item in after_snapshot.groups if item.group_id == group_id)
        assert group.created_by == "append"
        assert group.render_profile_id is not None
        assert group.voice_binding_id is not None
        assert group.segment_ids == [segment.segment_id for segment in after_snapshot.segments[2:]]

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        timeline_payload = timeline.json()
        assert timeline_payload["document_version"] == 2
        assert [entry["segment_id"] for entry in timeline_payload["segment_entries"]] == [
            segment.segment_id for segment in after_snapshot.segments
        ]


def test_append_into_existing_group_with_group_patch_rerenders_existing_group_members(test_app_settings, demo_binding_ref):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)

    with TestClient(app) as client:
        repository = app.state.edit_session_repository
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "binding_ref": demo_binding_ref,
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        active_session = repository.get_active_session()
        assert active_session is not None
        before_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert before_snapshot is not None
        first_segment = before_snapshot.segments[0].model_copy(deep=True)
        second_segment = before_snapshot.segments[1].model_copy(deep=True, update={"group_id": "group-1"})
        seeded_snapshot = before_snapshot.model_copy(
            deep=True,
            update={
                "segments": [first_segment, second_segment],
                "groups": [
                    SegmentGroup(
                        group_id="group-1",
                        name="group-1",
                        segment_ids=[second_segment.segment_id],
                        render_profile_id="profile-group",
                        voice_binding_id="binding-group",
                        created_by="manual",
                    )
                ],
                "render_profiles": [
                    RenderProfile(render_profile_id="profile-session", scope="session", name="session", speed=1.0),
                    RenderProfile(render_profile_id="profile-group", scope="group", name="group", speed=1.0),
                ],
                "voice_bindings": [
                    VoiceBinding(
                        voice_binding_id="binding-session",
                        scope="session",
                        binding_ref=demo_binding_ref,
                        voice_id="demo",
                        model_key="gpt-sovits-v2",
                    ),
                    VoiceBinding(
                        voice_binding_id="binding-group",
                        scope="group",
                        binding_ref=demo_binding_ref,
                        voice_id="demo",
                        model_key="gpt-sovits-v2",
                    ),
                ],
                "default_render_profile_id": "profile-session",
                "default_voice_binding_id": "binding-session",
            },
        )
        repository.save_snapshot(seeded_snapshot)
        baseline_calls = len(backend.segment_calls)

        append_response = client.post(
            "/v1/edit-session/append",
            json={
                "raw_text": "第三句。",
                "after_segment_id": second_segment.segment_id,
                "target_group_id": "group-1",
                "group_render_profile": {
                    "speed": 0.75
                },
            },
        )

        assert append_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        active_session = repository.get_active_session()
        assert active_session is not None
        after_snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        assert after_snapshot is not None

        assert len(backend.segment_calls) - baseline_calls == 2
        assert after_snapshot.segments[0].render_version == 1
        assert after_snapshot.segments[1].render_version == 2
        assert after_snapshot.segments[2].render_version == 1
        assert after_snapshot.groups[0].segment_ids == [after_snapshot.segments[1].segment_id, after_snapshot.segments[2].segment_id]
