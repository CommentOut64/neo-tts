from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store


def test_default_adapter_definition_store_exposes_qwen3_local_when_runtime_dependency_is_installed():
    store = build_default_adapter_definition_store(enable_gpt_sovits_local=False)

    assert "qwen3_tts_local" in [item.adapter_id for item in store.list_definitions()]
