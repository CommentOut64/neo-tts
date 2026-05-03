from pathlib import Path

from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore


def _build_workspace_service(registry_root: Path) -> WorkspaceService:
    return WorkspaceService(
        adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
        workspace_store=WorkspaceStore(registry_root),
        secret_store=SecretStore(registry_root),
    )


def test_workspace_service_resolve_binding_reference_merges_main_model_shared_assets_before_submodel_and_preset(
    tmp_path: Path,
):
    registry_root = tmp_path / "tts-registry"
    service = _build_workspace_service(registry_root)
    workspace = service.create_workspace(
        adapter_id="gpt_sovits_local",
        family_id="gpt_sovits_local_default",
        display_name="GPT-SoVITS Workspace",
        slug="gpt-sovits-workspace",
    )
    service.create_main_model(
        workspace_id=workspace.workspace_id,
        main_model_id="demo_voice",
        display_name="Demo Voice",
        source_type="local_package",
        main_model_metadata={"runtime": "gpt_sovits"},
        shared_assets={
            "bert": {"path": "pretrained/bert.bin", "fingerprint": "bert-fp"},
            "hubert": {"path": "pretrained/hubert.bin", "fingerprint": "hubert-fp"},
            "gpt_weight": {"path": "shared/should-be-overridden.ckpt", "fingerprint": "shared-gpt-fp"},
        },
    )
    service.create_submodel(
        workspace_id=workspace.workspace_id,
        main_model_id="demo_voice",
        submodel_id="weight_a",
        display_name="Weight A",
        instance_assets={
            "gpt_weight": {"path": "weights/demo.ckpt", "fingerprint": "gpt-fp"},
            "sovits_weight": {"path": "weights/demo.pth", "fingerprint": "sovits-fp"},
        },
    )
    service.create_preset(
        workspace_id=workspace.workspace_id,
        main_model_id="demo_voice",
        submodel_id="weight_a",
        preset_id="speaker_a",
        display_name="Speaker A",
        defaults={
            "reference_text": "测试参考文本",
            "reference_language": "zh",
        },
        preset_assets={
            "reference_audio": {"path": "refs/demo.wav", "fingerprint": "ref-fp"},
        },
    )

    resolved = service.resolve_binding_reference(
        BindingReference(
            workspace_id=workspace.workspace_id,
            main_model_id="demo_voice",
            submodel_id="weight_a",
            preset_id="speaker_a",
        )
    )

    assert resolved["resolved_assets"] == {
        "bert": {"path": "pretrained/bert.bin", "fingerprint": "bert-fp"},
        "hubert": {"path": "pretrained/hubert.bin", "fingerprint": "hubert-fp"},
        "gpt_weight": {"path": "weights/demo.ckpt", "fingerprint": "gpt-fp"},
        "sovits_weight": {"path": "weights/demo.pth", "fingerprint": "sovits-fp"},
        "reference_audio": {"path": "refs/demo.wav", "fingerprint": "ref-fp"},
    }
    assert resolved["gpt_path"] == "weights/demo.ckpt"
    assert resolved["sovits_path"] == "weights/demo.pth"
    assert resolved["reference_audio_path"] == "refs/demo.wav"
    assert resolved["reference_text"] == "测试参考文本"
    assert resolved["reference_language"] == "zh"
