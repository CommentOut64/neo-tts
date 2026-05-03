import json
from pathlib import Path

from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.gpt_sovits_facade import GPTSoVITSRegistryFacade
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_local_package(
    package_root: Path,
    *,
    package_id: str = "demo-gpt-sovits",
    display_name: str = "Demo Voice",
    preset_id: str = "speaker-a",
    preset_display_name: str = "Speaker A",
    gpt_weight: str = "weights/demo.ckpt",
    sovits_weight: str = "weights/demo.pth",
    reference_audio: str = "refs/demo.wav",
) -> Path:
    _write_json(
        package_root / "neo-tts-model.json",
        {
            "schema_version": 1,
            "package_id": package_id,
            "display_name": display_name,
            "adapter_id": "gpt_sovits_local",
            "source_type": "local_package",
            "instance": {
                "assets": {
                    "pretrained_base": "base",
                    "bert": "pretrained/bert.bin",
                }
            },
            "presets": [
                {
                    "preset_id": preset_id,
                    "display_name": preset_display_name,
                    "assets": {
                        "gpt_weight": gpt_weight,
                        "sovits_weight": sovits_weight,
                        "reference_audio": reference_audio,
                    },
                    "defaults": {
                        "reference_text": "测试参考文本",
                        "reference_language": "zh",
                        "speed": 1.0,
                    },
                }
            ],
        },
    )
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / gpt_weight, "ckpt")
    _write_text(package_root / sovits_weight, "pth")
    _write_text(package_root / reference_audio, "wav")
    return package_root


def _build_workspace_service(registry_root: Path) -> WorkspaceService:
    return WorkspaceService(
        adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
        workspace_store=WorkspaceStore(registry_root),
        secret_store=SecretStore(registry_root),
    )


def test_gpt_sovits_registry_facade_imports_local_package_into_fixed_workspace_main_model(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="GPT-SoVITS Workspace",
        slug="gpt-sovits-workspace",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )

    imported = facade.import_model_package_to_workspace(
        workspace_id=workspace.workspace_id,
        source_path=_build_local_package(tmp_path / "source-package"),
        storage_mode="managed",
    )

    assert imported.main_model.main_model_id == "gpt_sovits"
    assert imported.main_model.shared_assets["bert"]["source_path"].endswith("pretrained/bert.bin")
    assert imported.submodels[0].submodel_id == "speaker_a"
    assert imported.submodels[0].instance_assets["gpt_weight"]["source_path"].endswith("weights/demo.ckpt")
    assert imported.presets[0].preset_id == "default"
    assert imported.presets[0].preset_assets["reference_audio"]["source_path"].endswith("refs/demo.wav")
    assert imported.presets[0].defaults["reference_text"] == "测试参考文本"

    tree = workspace_service.get_workspace_tree(workspace.workspace_id)
    assert [item.main_model_id for item in tree.main_models] == ["gpt_sovits"]
    assert tree.main_models[0].submodels[0].submodel_id == "speaker_a"
    assert tree.main_models[0].submodels[0].presets[0].preset_id == "default"


def test_gpt_sovits_registry_facade_keeps_one_main_model_when_importing_multiple_weights(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="GPT-SoVITS Workspace",
        slug="gpt-sovits-workspace",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )

    facade.import_model_package_to_workspace(
        workspace_id=workspace.workspace_id,
        source_path=_build_local_package(
            tmp_path / "source-package-a",
            package_id="demo-gpt-sovits-a",
            display_name="Voice A",
            preset_id="speaker-a",
            preset_display_name="Speaker A",
            gpt_weight="weights/a.ckpt",
            sovits_weight="weights/a.pth",
            reference_audio="refs/a.wav",
        ),
        storage_mode="managed",
    )
    facade.import_model_package_to_workspace(
        workspace_id=workspace.workspace_id,
        source_path=_build_local_package(
            tmp_path / "source-package-b",
            package_id="demo-gpt-sovits-b",
            display_name="Voice B",
            preset_id="speaker-b",
            preset_display_name="Speaker B",
            gpt_weight="weights/b.ckpt",
            sovits_weight="weights/b.pth",
            reference_audio="refs/b.wav",
        ),
        storage_mode="managed",
    )

    tree = workspace_service.get_workspace_tree(workspace.workspace_id)
    assert [item.main_model_id for item in tree.main_models] == ["gpt_sovits"]
    assert sorted(item.submodel_id for item in tree.main_models[0].submodels) == ["speaker_a", "speaker_b"]


def test_gpt_sovits_registry_facade_imports_legacy_voice_into_formal_workspace_tree(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="Formal GPT-SoVITS",
        slug="formal-gpt-sovits",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )

    imported = facade.import_legacy_voice_to_workspace(
        workspace_id=workspace.workspace_id,
        voice_name="Demo Voice",
        raw_config={
            "gpt_path": "weights/demo.ckpt",
            "sovits_path": "weights/demo.pth",
            "ref_audio": "refs/demo.wav",
            "ref_text": "hello world",
            "ref_lang": "en",
            "defaults": {
                "speed": 1.0,
            },
        },
    )

    assert imported.main_model.main_model_id == "demo_voice"
    assert imported.submodels[0].submodel_id == "default"
    assert imported.submodels[0].instance_assets["gpt_weight"]["path"] == "weights/demo.ckpt"
    assert imported.submodels[0].instance_assets["sovits_weight"]["path"] == "weights/demo.pth"
    assert imported.presets[0].preset_id == "default"
    assert imported.presets[0].preset_assets["reference_audio"]["path"] == "refs/demo.wav"
    assert imported.presets[0].defaults["reference_text"] == "hello world"
    assert imported.presets[0].defaults["reference_language"] == "en"

    resolved = workspace_service.resolve_binding_reference(
        {
            "workspace_id": workspace.workspace_id,
            "main_model_id": "demo_voice",
            "submodel_id": "default",
            "preset_id": "default",
        }
    )
    assert resolved["gpt_path"] == "weights/demo.ckpt"
    assert resolved["sovits_path"] == "weights/demo.pth"
    assert resolved["reference_audio_path"] == "refs/demo.wav"


def test_gpt_sovits_registry_facade_bulk_imports_legacy_voices_into_formal_workspace_tree(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="Formal GPT-SoVITS",
        slug="formal-gpt-sovits",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )

    imported = facade.import_legacy_voices_to_workspace(
        workspace_id=workspace.workspace_id,
        voices_by_name={
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            },
            "Second Voice": {
                "gpt_path": "weights/second.ckpt",
                "sovits_path": "weights/second.pth",
                "ref_audio": "refs/second.wav",
                "ref_text": "second world",
                "ref_lang": "zh",
            },
        },
    )

    assert [item.main_model.main_model_id for item in imported] == ["demo_voice", "second_voice"]
    tree = workspace_service.get_workspace_tree(workspace.workspace_id)
    assert [item.main_model_id for item in tree.main_models] == ["demo_voice", "second_voice"]


def test_gpt_sovits_registry_facade_can_consolidate_legacy_voices_under_single_main_model(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="GPT-SoVITS",
        slug="gpt-sovits",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )

    imported = facade.import_legacy_voices_as_submodels_to_workspace(
        workspace_id=workspace.workspace_id,
        main_model_id="gpt_sovits",
        main_model_display_name="GPT-SoVITS",
        voices_by_name={
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            },
            "Second Voice": {
                "gpt_path": "weights/second.ckpt",
                "sovits_path": "weights/second.pth",
                "ref_audio": "refs/second.wav",
                "ref_text": "second world",
                "ref_lang": "zh",
            },
        },
    )

    assert imported.main_model.main_model_id == "gpt_sovits"
    assert [item.submodel_id for item in imported.submodels] == ["demo_voice", "second_voice"]
    assert [item.main_model_id for item in workspace_service.get_workspace_tree(workspace.workspace_id).main_models] == [
        "gpt_sovits"
    ]
    resolved = workspace_service.resolve_binding_reference(
        {
            "workspace_id": workspace.workspace_id,
            "main_model_id": "gpt_sovits",
            "submodel_id": "demo_voice",
            "preset_id": "default",
        }
    )
    assert resolved["gpt_path"] == "weights/demo.ckpt"
    assert resolved["reference_audio_path"] == "refs/demo.wav"


def test_gpt_sovits_registry_facade_can_restructure_workspace_to_single_main_model(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    workspace_service = _build_workspace_service(registry_root)
    workspace = workspace_service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="GPT-SoVITS",
        slug="gpt-sovits",
    )
    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
            model_registry=ModelRegistry(registry_root),
            secret_store=SecretStore(registry_root),
        ),
    )
    facade.import_legacy_voices_to_workspace(
        workspace_id=workspace.workspace_id,
        voices_by_name={
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            },
            "Second Voice": {
                "gpt_path": "weights/second.ckpt",
                "sovits_path": "weights/second.pth",
                "ref_audio": "refs/second.wav",
                "ref_text": "second world",
                "ref_lang": "zh",
            },
        },
    )

    rebuilt = facade.restructure_workspace_to_single_main_model(
        workspace_id=workspace.workspace_id,
        target_main_model_id="gpt_sovits",
        target_main_model_display_name="GPT-SoVITS",
    )

    assert rebuilt.main_model.main_model_id == "gpt_sovits"
    assert [item.main_model_id for item in workspace_service.get_workspace_tree(workspace.workspace_id).main_models] == [
        "gpt_sovits"
    ]
    assert [item.submodel_id for item in rebuilt.submodels] == ["demo_voice", "second_voice"]
    resolved = workspace_service.resolve_binding_reference(
        {
            "workspace_id": workspace.workspace_id,
            "main_model_id": "gpt_sovits",
            "submodel_id": "second_voice",
            "preset_id": "default",
        }
    )
    assert resolved["gpt_path"] == "weights/second.ckpt"
    assert resolved["reference_audio_path"] == "refs/second.wav"
