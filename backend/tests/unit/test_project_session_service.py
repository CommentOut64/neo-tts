from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.app.services.project_session_service import ProjectSessionService
from backend.app.services.project_store import NeoWriteBusyError, ProjectStore
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    ReferenceBindingOverride,
    RenderProfile,
    VoiceBinding,
)
from backend.tests.unit.test_project_store import payload
from backend.app.services.session_reference_asset_service import SessionReferenceAssetService
from backend.app.inference.editable_types import build_boundary_asset_id


def test_workspace_save_and_open_roundtrip(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    revision = service.save(payload())
    assert revision == 1
    project_file = root / "p1.neo"
    assert project_file.is_file()
    assert json.loads((root / "workspace.json").read_text())["dirty"] is False

    restored = service.open_project(project_file)
    assert restored["project"]["project_id"] == "p1"
    assert restored["project"]["head_snapshot_id"] == "s1"
    assert restored["project"]["workspace_id"] == service.workspace_id
    assert json.loads((service.workspace_path / "workspace.json").read_text())["last_save_revision"] == 1


def test_first_save_lazily_creates_workspace(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)

    revision = service.save(payload())

    assert revision == 1
    assert service.workspace_id
    project_file = service.workspace_path / "p1.neo"
    assert project_file.is_file()
    assert ProjectStore(project_file).load()["project"]["save_revision"] == 1


def test_invalid_first_save_does_not_create_workspace(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)

    with pytest.raises(ValueError, match="project payload"):
        service.save({})

    assert service.workspace_id is None
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_first_save_with_nonzero_token_preserves_initialization_error(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    token = service.capture_token({"project": {"project_id": "p1", "save_revision": 3}})

    with pytest.raises(RuntimeError, match="workspace not initialized"):
        service.save(payload(), token)

    assert service.workspace_id is None
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_first_save_as_lazily_creates_workspace(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    target = tmp_path / "p1-copy.neo"

    returned = service.save(payload(), target=target, force_partial=True)

    assert returned == 0
    assert service.workspace_id
    assert target.is_file()
    assert ProjectStore(target).load()["project"]["save_revision"] == 1


def test_capture_token_preserves_expected_revision(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    service.create_workspace(project_id="p1", workspace_id="w1")
    token = service.capture_token(
        {"project": {"project_id": "p1", "save_revision": 4, "draft_revision": 2}}
    )
    assert token.expected_save_revision == 4
    assert token.draft_revision == 2


def test_deferred_model_replacement_status_stays_read_only(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)

    for status in ("replacement_checking", "replacement_compatible"):
        capability = service.capability_for_status(status)
        assert capability == {
            "play": True,
            "export": True,
            "edit": False,
            "render": False,
            "boundary": False,
        }


def test_open_deferred_replacement_status_does_not_unlock_editing(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    captured = payload()
    captured["project"]["model_resolution_status"] = "replacement_compatible"
    assert source.save(captured) == 1

    target = ProjectSessionService(user_data_root=tmp_path / "target")
    restored = target.open_project(source_root / "p1.neo")

    assert restored["project"]["model_resolution_status"] == "replacement_compatible"
    assert restored["project"]["capability"]["edit"] is False
    assert target.current_capability["render"] is False


def test_workspace_rejects_path_traversal_project_id(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    with pytest.raises(ValueError, match="project id"):
        service.create_workspace(project_id="../outside", workspace_id="w1")


def test_second_save_increments_file_revision(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    service.create_workspace(project_id="p1", workspace_id="w1")
    assert service.save(payload()) == 1
    token = service.capture_token({"project": {"project_id": "p1", "save_revision": 1}})
    assert service.save(payload(), token) == 2


def test_stale_capture_saves_captured_revision_but_preserves_dirty_flag(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    service.create_workspace(project_id="p1", workspace_id="w1")
    captured = payload()
    captured["project"]["head_revision"] = 2
    token = service.capture_token(
        {
            "project": {
                "project_id": "p1",
                "head_revision": 1,
                "save_revision": 0,
            }
        }
    )

    assert service.save(captured, token) == 1
    assert service.last_save_stale is True
    assert json.loads((service.workspace_path / "workspace.json").read_text())["dirty"] is True


def test_existing_target_save_uses_incremental_sqlite_path(tmp_path, monkeypatch):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    service.save(payload())
    target = root / "p1.neo"
    original_replace = __import__("os").replace
    monkeypatch.setattr("backend.app.services.project_session_service.os.replace", lambda *_: (_ for _ in ()).throw(AssertionError("ordinary save must not replace target")))
    token = service.capture_token({"project": {"project_id": "p1", "save_revision": 1}})
    assert service.save(payload(), token) == 2
    assert target.is_file()
    monkeypatch.setattr("backend.app.services.project_session_service.os.replace", original_replace)


def test_workspace_writer_lock_rejects_second_service_writer(tmp_path):
    first = ProjectSessionService(user_data_root=tmp_path)
    first.create_workspace(project_id="p1", workspace_id="w1")
    second = ProjectSessionService(user_data_root=tmp_path, workspace_id="w1")

    with first._workspace_write_lock():  # noqa: SLF001 - lock contract regression
        with pytest.raises(NeoWriteBusyError):
            with second._workspace_write_lock():  # noqa: SLF001
                pass


def test_save_as_existing_target_uses_partial_replace_path(tmp_path, monkeypatch):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    assert service.save(payload()) == 1
    target = root / "p1-copy.neo"
    target.write_bytes((root / "p1.neo").read_bytes())
    calls: list[tuple[object, object]] = []
    original_replace = __import__("os").replace

    def observe_replace(source, destination):
        calls.append((source, destination))
        return original_replace(source, destination)

    monkeypatch.setattr("backend.app.services.project_session_service.os.replace", observe_replace)
    assert service.save(payload(), target=target, force_partial=True) == 1
    assert calls
    assert calls[-1][1] == target


def test_save_as_new_target_accepts_source_capture_token(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    assert service.save(payload()) == 1
    token = service.capture_token({"project": {"project_id": "p1", "save_revision": 1}})

    target = root / "p1-copy.neo"
    assert service.save(payload(), token, target=target, force_partial=True) == 1
    assert ProjectStore(target).load()["project"]["save_revision"] == 1


def test_save_as_keeps_source_metadata_and_returns_active_revision(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    assert service.save(payload()) == 1
    assert service.save(payload()) == 2
    service.mark_dirty(True)

    metadata_path = root / "workspace.json"
    before = json.loads(metadata_path.read_text(encoding="utf-8"))
    target = root / "p1-copy.neo"

    returned = service.save(payload(), target=target, force_partial=True)

    after = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert returned == 2
    assert ProjectStore(target).load()["project"]["save_revision"] == 1
    assert after["last_save_revision"] == before["last_save_revision"] == 2
    assert after["dirty"] is before["dirty"] is True
    assert after["last_opened_at"] == before["last_opened_at"]


def test_save_after_save_as_continues_writing_active_source(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    root = service.create_workspace(project_id="p1", workspace_id="w1")
    assert service.save(payload()) == 1
    assert service.save(payload()) == 2
    target = root / "p1-copy.neo"
    assert service.save(payload(), target=target, force_partial=True) == 2

    assert service.save(payload()) == 3
    assert ProjectStore(root / "p1.neo").load()["project"]["save_revision"] == 3
    assert ProjectStore(target).load()["project"]["save_revision"] == 1


def test_save_pins_captured_assets_for_the_entire_writer_lifecycle(tmp_path, monkeypatch):
    service = ProjectSessionService(user_data_root=tmp_path)
    service.create_workspace(project_id="p1", workspace_id="w1")
    observed: list[set[str]] = []

    def fake_save_impl(captured, token=None, *, target=None, force_partial=False):
        del captured, token, target, force_partial
        observed.append(service.pinned_asset_ids())
        return 1

    monkeypatch.setattr(service, "_save_impl", fake_save_impl)
    assert service.save(payload()) == 1
    assert observed == [{"a1"}]
    assert service.pinned_asset_ids() == set()


def test_gc_coordinator_keeps_pinned_asset_under_workspace_mutex(tmp_path):
    service = ProjectSessionService(user_data_root=tmp_path)
    store = EditAssetStore(
        project_root=tmp_path,
        assets_dir=tmp_path / "assets",
        export_root=tmp_path / "exports",
        staging_ttl_seconds=60,
    )
    pinned = store.segment_asset_path("render-pinned")
    orphan = store.segment_asset_path("render-orphan")
    pinned.mkdir(parents=True)
    orphan.mkdir(parents=True)
    (pinned / "audio.wav").write_bytes(b"pinned")
    (orphan / "audio.wav").write_bytes(b"orphan")

    with service.pin_assets(["render-pinned"]):
        report = service.collect_unreferenced_formal_assets(set(), asset_store=store)

    assert pinned.exists()
    assert not orphan.exists()
    assert any(path.name == "render-orphan" for path in report.deleted_asset_paths)


def test_save_hydrates_existing_formal_asset_bytes_before_writing_neo(tmp_path):
    store = EditAssetStore(
        project_root=tmp_path,
        assets_dir=tmp_path / "assets",
        export_root=tmp_path / "exports",
        staging_ttl_seconds=60,
    )
    asset_dir = store.segment_asset_path("a1")
    asset_dir.mkdir(parents=True)
    (asset_dir / "audio.wav").write_bytes(b"materialized-audio")
    service = ProjectSessionService(user_data_root=tmp_path, asset_store=store)
    service.create_workspace(project_id="p1", workspace_id="w1")
    captured = payload()
    captured["assets"][0]["ready"] = 1
    captured["assets"][0].pop("blob_sha256", None)
    captured["assets"][0]["byte_count"] = 0
    captured["blobs"] = []

    assert service.save(captured) == 1
    loaded = ProjectStore(service.workspace_path / "p1.neo").load()
    assert loaded["assets"][0]["ready"] == 1
    assert loaded["blobs"][0]["data"] == b"materialized-audio"


def test_open_project_uses_s2_catalog_resolver_without_rebinding_assets(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    assert source.save(payload()) == 1

    class Catalog:
        def resolve(self, **kwargs):
            assert kwargs["model_id"] == "m1"
            assert kwargs["model_revision"] == "r1"
            return (
                SimpleNamespace(
                    model_id="m1",
                    model_revision="r1",
                    gpt_content_sha256="",
                    sovits_content_sha256="",
                    capabilities=("cpu",),
                ),
                SimpleNamespace(preset_id="m1:default", preset_revision="p1"),
            )

    target = ProjectSessionService(user_data_root=tmp_path / "target", model_catalog=Catalog())
    restored = target.open_project(source_root / "p1.neo")

    assert restored["project"]["model_resolution_status"] == "exact"
    assert restored["project"]["diagnostics_json"]["code"] == "MODEL_RESOLVED"
    assert restored["project"]["capability"]["edit"] is True


def test_open_project_keeps_legacy_gpt_sovits_runtime_editable(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    legacy = payload()
    legacy["project"]["model_identity"] = {
        "model_id": "gpt-sovits-v2",
        "model_revision": "",
        "preset_id": "demo",
        "preset_revision": "",
    }
    assert source.save(legacy) == 1

    class Catalog:
        def resolve(self, **kwargs):
            raise LookupError(f"unexpected catalog lookup: {kwargs}")

    target = ProjectSessionService(user_data_root=tmp_path / "target", model_catalog=Catalog())
    restored = target.open_project(source_root / "p1.neo")

    assert restored["project"]["model_resolution_status"] == "exact"
    assert restored["project"]["diagnostics_json"]["code"] == "MODEL_LEGACY_RUNTIME"
    assert restored["project"]["capability"]["edit"] is True


def test_open_project_missing_catalog_model_becomes_read_only_degraded(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    assert source.save(payload()) == 1

    class MissingCatalog:
        def resolve(self, **kwargs):
            del kwargs
            raise LookupError("model not found")

    target = ProjectSessionService(user_data_root=tmp_path / "target", model_catalog=MissingCatalog())
    restored = target.open_project(source_root / "p1.neo")

    assert restored["project"]["model_resolution_status"] == "read_only_degraded"
    assert restored["project"]["diagnostics_json"]["code"] == "MODEL_MISSING"
    assert restored["project"]["capability"] == {
        "play": True,
        "export": True,
        "edit": False,
        "render": False,
        "boundary": False,
    }


def test_open_project_catalog_model_with_missing_weight_path_is_read_only(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    assert source.save(payload()) == 1

    class Catalog:
        def resolve(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(
                    model_id="m1",
                    model_revision="r1",
                    gpt_path_hint=str(tmp_path / "missing.ckpt"),
                    sovits_path_hint=str(tmp_path / "missing.pth"),
                    gpt_content_sha256="",
                    sovits_content_sha256="",
                    capabilities=(),
                ),
                SimpleNamespace(preset_id="m1:default", preset_revision="p1"),
            )

    target = ProjectSessionService(user_data_root=tmp_path / "target", model_catalog=Catalog())
    restored = target.open_project(source_root / "p1.neo")

    assert restored["project"]["model_resolution_status"] == "read_only_degraded"
    assert restored["project"]["diagnostics_json"]["code"] == "MODEL_MISSING"


def test_open_project_installs_formal_state_into_active_edit_repository(tmp_path):
    source = ProjectSessionService(user_data_root=tmp_path / "source")
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    assert source.save(payload()) == 1
    repository = EditSessionRepository(project_root=tmp_path / "target", db_file=tmp_path / "target" / "edit.db")
    repository.initialize_schema()

    target = ProjectSessionService(user_data_root=tmp_path / "target", edit_session_repository=repository)
    target.open_project(source_root / "p1.neo")

    active = repository.get_active_session()
    assert active is not None
    assert active.document_id == "p1"
    assert active.initialize_request is not None
    assert active.initialize_request.raw_text == "hello。"
    installed = repository.get_snapshot(active.head_snapshot_id or "")
    assert installed is not None
    assert installed.segments[0].segment_id == "seg1"


def test_timeline_nested_blocks_are_captured_and_restored(tmp_path):
    store = EditAssetStore(
        project_root=tmp_path / "source",
        assets_dir=tmp_path / "source" / "assets",
        export_root=tmp_path / "source" / "exports",
        staging_ttl_seconds=60,
    )
    timeline_id = "timeline-1"
    block_id = "block-1"
    timeline_dir = store.timeline_manifest_path(timeline_id)
    block_dir = store.block_asset_path(block_id)
    timeline_dir.mkdir(parents=True)
    block_dir.mkdir(parents=True)
    (timeline_dir / "manifest.json").write_text(
        json.dumps({"block_entries": [{"block_asset_id": block_id}]}), encoding="utf-8"
    )
    (block_dir / "audio.wav").write_bytes(b"wav-bytes")
    (block_dir / "metadata.json").write_text(
        json.dumps({"block_id": block_id, "audio_sample_count": 1}), encoding="utf-8"
    )
    service = ProjectSessionService(user_data_root=tmp_path / "source", asset_store=store)
    captured = service._augment_timeline_block_assets({
        "assets": [{"asset_id": timeline_id, "kind": "timeline", "role": "timeline", "ready": 0}],
        "asset_refs": [],
    })
    block = next(item for item in captured["assets"] if item["asset_id"] == block_id)
    assert block["role"] == "block"
    hydrated = service._hydrate_payload_assets(captured)
    hydrated_block = next(item for item in hydrated["assets"] if item["asset_id"] == block_id)
    assert hydrated_block["ready"] == 1
    assert any(blob["data"] == b"wav-bytes" for blob in hydrated["blobs"])


def test_snapshot_capture_includes_deterministic_boundary_assets():
    left = EditableSegment(
        segment_id="left",
        document_id="p1",
        order_key=0,
        stem="left",
        text_language="en",
        render_version=2,
        render_asset_id="left-audio",
    )
    right = EditableSegment(
        segment_id="right",
        document_id="p1",
        order_key=1,
        stem="right",
        text_language="en",
        render_version=3,
        render_asset_id="right-audio",
    )
    edge = EditableEdge(
        edge_id="edge-left-right",
        document_id="p1",
        left_segment_id="left",
        right_segment_id="right",
        edge_version=4,
        boundary_strategy="crossfade_only",
        effective_boundary_strategy="crossfade_only",
    )
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="p1",
        snapshot_kind="head",
        document_version=1,
        segments=[left, right],
        edges=[edge],
    )

    captured = ProjectSessionService._snapshot_to_payload(snapshot)

    boundary = next(asset for asset in captured["_assets"] if asset["role"] == "boundary")
    assert boundary["asset_id"] == build_boundary_asset_id(
        left_segment_id="left",
        left_render_version=2,
        right_segment_id="right",
        right_render_version=3,
        edge_version=4,
        boundary_strategy="crossfade_only",
    )
    assert {
        "owner_type": "edge",
        "owner_id": "edge-left-right",
        "asset_id": boundary["asset_id"],
        "purpose": "boundary",
    } in captured["_asset_refs"]


def test_save_uses_edit_repository_snapshots_and_preserves_baseline_roots(tmp_path):
    repository = EditSessionRepository(project_root=tmp_path, db_file=tmp_path / "edit.db")
    repository.initialize_schema()
    baseline = DocumentSnapshot(
        snapshot_id="baseline-1",
        document_id="p1",
        snapshot_kind="baseline",
        document_version=1,
        segments=[EditableSegment(segment_id="baseline-seg", document_id="p1", order_key=0, stem="baseline", text_language="zh")],
    )
    head = baseline.model_copy(
        deep=True,
        update={
            "snapshot_id": "head-2",
            "snapshot_kind": "head",
            "document_version": 2,
            "segments": [EditableSegment(segment_id="head-seg", document_id="p1", order_key=0, stem="head", text_language="zh")],
        },
    )
    repository.save_snapshot(baseline)
    repository.save_snapshot(head)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="p1",
            session_status="ready",
            baseline_snapshot_id="baseline-1",
            head_snapshot_id="head-2",
        )
    )
    service = ProjectSessionService(user_data_root=tmp_path, edit_session_repository=repository)
    service.create_workspace(project_id="p1", workspace_id="w1")

    captured = payload()
    assert service.save(captured) == 1
    loaded = ProjectStore(service.workspace_path / "p1.neo").load()
    assert {item["snapshot_id"] for item in loaded["snapshots"]} >= {"baseline-1", "head-2"}
    assert loaded["project"]["baseline_snapshot_id"] == "baseline-1"


def test_save_and_open_roundtrip_freezes_session_reference_audio(tmp_path):
    source_store = EditAssetStore(
        project_root=tmp_path / "source",
        assets_dir=tmp_path / "source" / "assets",
        export_root=tmp_path / "source" / "exports",
        staging_ttl_seconds=60,
    )
    source_repository = EditSessionRepository(
        project_root=tmp_path / "source",
        db_file=tmp_path / "source" / "edit.db",
    )
    source_repository.initialize_schema()
    reference_service = SessionReferenceAssetService(assets_root=source_store.assets_root)
    reference = reference_service.create_asset(
        session_id="p1",
        filename="reference.wav",
        payload=b"reference-audio",
        binding_key="voice-a:model-a",
        reference_text="参考文本",
        reference_language="zh",
    )
    profile = RenderProfile(
        render_profile_id="profile-1",
        scope="session",
        name="session-default",
        reference_overrides_by_binding={
            "voice-a:model-a": ReferenceBindingOverride(
                session_reference_asset_id=reference.reference_asset_id,
                reference_identity=f"p1:{reference.reference_asset_id}",
                reference_audio_fingerprint=reference.audio_fingerprint,
                reference_audio_path=reference.audio_path,
                reference_text=reference.reference_text,
                reference_text_fingerprint=reference.reference_text_fingerprint,
                reference_language=reference.reference_language,
            )
        },
    )
    binding = VoiceBinding(
        voice_binding_id="binding-1",
        scope="session",
        voice_id="voice-a",
        model_key="model-a",
    )
    snapshot = DocumentSnapshot(
        snapshot_id="head-reference",
        document_id="p1",
        snapshot_kind="head",
        document_version=1,
        render_profiles=[profile],
        voice_bindings=[binding],
        default_render_profile_id=profile.render_profile_id,
        default_voice_binding_id=binding.voice_binding_id,
        segments=[
            EditableSegment(
                segment_id="segment-reference",
                document_id="p1",
                order_key=0,
                stem="hello",
                text_language="en",
                voice_binding_id=binding.voice_binding_id,
                render_profile_id=profile.render_profile_id,
            )
        ],
    )
    source_repository.save_snapshot(snapshot)
    source_repository.upsert_active_session(
        ActiveDocumentState(
            document_id="p1",
            session_status="ready",
            head_snapshot_id=snapshot.snapshot_id,
        )
    )
    source = ProjectSessionService(
        user_data_root=tmp_path / "source",
        asset_store=source_store,
        edit_session_repository=source_repository,
    )
    source_root = source.create_workspace(project_id="p1", workspace_id="w1")
    assert source.save(payload("p1")) == 1

    saved = ProjectStore(source_root / "p1.neo").load()
    refs = saved["references"]
    assert len(refs) == 1
    assert refs[0]["role"] == "speaker"
    assert refs[0]["text_hash"] == reference.reference_text_fingerprint
    ref_asset = next(item for item in saved["assets"] if item["kind"] == "reference_audio")
    assert ref_asset["ready"] == 1
    assert any(blob["data"] == b"reference-audio" for blob in saved["blobs"])
    assert any(item["owner_type"] == "reference" for item in saved["asset_refs"])

    target_store = EditAssetStore(
        project_root=tmp_path / "target",
        assets_dir=tmp_path / "target" / "assets",
        export_root=tmp_path / "target" / "exports",
        staging_ttl_seconds=60,
    )
    target_repository = EditSessionRepository(
        project_root=tmp_path / "target",
        db_file=tmp_path / "target" / "edit.db",
    )
    target_repository.initialize_schema()
    target = ProjectSessionService(
        user_data_root=tmp_path / "target",
        asset_store=target_store,
        edit_session_repository=target_repository,
    )
    restored = target.open_project(source_root / "p1.neo")
    assert restored["references"][0]["status"] == "present"
    restored_reference = target_repository.get_snapshot("head-reference")
    assert restored_reference is not None
    restored_override = restored_reference.render_profiles[0].reference_overrides_by_binding["voice-a:model-a"]
    assert restored_override.session_reference_asset_id == reference.reference_asset_id
    assert restored_override.reference_audio_path is not None
    assert Path(restored_override.reference_audio_path).is_file()
    assert Path(restored_override.reference_audio_path).read_bytes() == b"reference-audio"


def test_import_legacy_session_converts_snapshot_tables(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    source = legacy / "session.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (snapshot_id TEXT, document_id TEXT, document_version INTEGER, created_at TEXT, payload TEXT);
            CREATE TABLE segments (snapshot_id TEXT, segment_id TEXT, document_id TEXT, order_key INTEGER, payload TEXT);
            CREATE TABLE edges (snapshot_id TEXT, edge_id TEXT, document_id TEXT, left_segment_id TEXT, right_segment_id TEXT, edge_order_key INTEGER, payload TEXT);
            """
        )
        conn.execute("INSERT INTO snapshots VALUES ('s1','doc1',1,'2026-01-01T00:00:00Z',?)", (json.dumps({"snapshot_kind": "head"}),))
        conn.execute("INSERT INTO segments VALUES ('s1','seg1','doc1',0,?)", (json.dumps({"segment_id": "seg1", "text": {"value": "hello"}}),))
        conn.commit()
    service = ProjectSessionService(user_data_root=tmp_path / "imported")
    root = service.import_legacy_session(source)
    restored = ProjectStore(root / "session.db").load()
    assert restored["project"]["head_snapshot_id"] == "s1"
    imported = next(item for item in restored["snapshots"] if item["snapshot_id"] == "s1")
    assert imported["segments"][0]["segment_id"] == "seg1"


def test_import_legacy_formal_roles_map_to_v1_asset_kinds(tmp_path):
    legacy = tmp_path / "legacy-with-assets"
    legacy.mkdir()
    source = legacy / "session.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (snapshot_id TEXT, document_id TEXT, document_version INTEGER, created_at TEXT, payload TEXT);
            CREATE TABLE segments (snapshot_id TEXT, segment_id TEXT, document_id TEXT, order_key INTEGER, payload TEXT);
            CREATE TABLE edges (snapshot_id TEXT, edge_id TEXT, document_id TEXT, left_segment_id TEXT, right_segment_id TEXT, edge_order_key INTEGER, payload TEXT);
            """
        )
        conn.execute(
            "INSERT INTO snapshots VALUES ('s1','doc1',1,'2026-01-01T00:00:00Z',?)",
            (
                json.dumps(
                    {
                        "snapshot_kind": "head",
                        "block_ids": ["block-1"],
                        "composition_manifest_id": "composition-1",
                        "timeline_manifest_id": "timeline-1",
                    }
                ),
            ),
        )
        conn.commit()

    assets_root = legacy / "assets" / "formal"
    (assets_root / "blocks" / "block-1").mkdir(parents=True)
    (assets_root / "compositions" / "composition-1").mkdir(parents=True)
    (assets_root / "timelines" / "timeline-1").mkdir(parents=True)
    (assets_root / "blocks" / "block-1" / "audio.wav").write_bytes(b"block")
    (assets_root / "compositions" / "composition-1" / "metadata.json").write_bytes(b"composition")
    (assets_root / "timelines" / "timeline-1" / "manifest.json").write_bytes(b"timeline")

    service = ProjectSessionService(user_data_root=tmp_path / "imported-with-assets")
    root = service.import_legacy_session(source)
    restored = ProjectStore(root / "session.db").load()
    by_id = {item["asset_id"]: item for item in restored["assets"]}

    assert by_id["block-1"]["kind"] == "formal"
    assert by_id["block-1"]["role"] == "block"
    assert by_id["composition-1"]["kind"] == "formal"
    assert by_id["composition-1"]["role"] == "composition"
    assert by_id["timeline-1"]["kind"] == "timeline"
