from pydantic import ValidationError

from backend.app.inference.block_adapter_types import ResolvedModelBinding
from backend.app.inference.adapter_definition import OverridePolicy
from backend.app.tts_registry.types import ModelInstance, ModelPreset


def test_model_instance_and_preset_are_json_serializable():
    preset = ModelPreset(
        preset_id="preset-default",
        display_name="Default",
        kind="imported",
        status="ready",
        fixed_fields={"speaker_id": "speaker-a"},
        defaults={"speed": 1.0, "reference_text": "测试参考文本"},
        preset_assets={
            "gpt_weight": {
                "path": "weights/demo.ckpt",
                "fingerprint": "gpt-fp",
            },
            "reference_audio": {
                "path": "refs/demo.wav",
                "fingerprint": "ref-fp",
            },
        },
        override_policy=OverridePolicy(
            overridable_assets=["reference_audio"],
            overridable_fields=["reference_text", "synthesis.*"],
        ),
        fingerprint="preset-fp",
    )
    instance = ModelInstance(
        model_instance_id="model-demo",
        adapter_id="gpt_sovits_local",
        source_type="local_package",
        display_name="Demo Voice",
        status="ready",
        storage_mode="managed",
        instance_assets={
            "bert": {
                "path": "pretrained/bert",
                "fingerprint": "bert-fp",
            }
        },
        endpoint=None,
        account_binding=None,
        presets=[preset],
        fingerprint="model-fp",
    )

    payload = instance.model_dump(mode="json")

    assert payload["adapter_id"] == "gpt_sovits_local"
    assert payload["source_type"] == "local_package"
    assert payload["presets"][0]["override_policy"]["overridable_fields"] == [
        "reference_text",
        "synthesis.*",
    ]
    assert payload["instance_assets"]["bert"]["fingerprint"] == "bert-fp"


def test_model_preset_rejects_invalid_status():
    try:
        ModelPreset(
            preset_id="preset-default",
            display_name="Default",
            kind="imported",
            status="needs_secret",
            fingerprint="preset-fp",
        )
    except ValidationError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("ModelPreset 应拒绝 instance 专属状态。")


def test_resolved_model_binding_is_reused_from_block_adapter_types():
    binding = ResolvedModelBinding(
        adapter_id="gpt_sovits_local",
        model_instance_id="model-demo",
        preset_id="preset-default",
        resolved_assets={"gpt_weight": "weights/demo.ckpt"},
        resolved_reference={"reference_id": "ref-1"},
        resolved_parameters={"speed": 1.0},
        secret_handles={"api_key": "secret://demo"},
        binding_fingerprint="binding-fp",
    )

    payload = binding.model_dump(mode="json")

    assert payload["binding_fingerprint"] == "binding-fp"
    assert payload["secret_handles"] == {"api_key": "secret://demo"}
