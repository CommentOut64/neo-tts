from __future__ import annotations

import json
import sys

from backend.app.core.settings import get_settings
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.migration_service import TtsRegistryMigrationService
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore


def main() -> int:
    settings = get_settings()
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    workspace_service = WorkspaceService(
        adapter_store=build_default_adapter_definition_store(
            enable_gpt_sovits_local=getattr(settings, "gpt_sovits_adapter_installed", True),
        ),
        workspace_store=WorkspaceStore(registry_root),
        secret_store=SecretStore(registry_root),
    )
    migration_service = TtsRegistryMigrationService(
        workspace_service=workspace_service,
        registry_root=registry_root,
    )
    created = migration_service.migrate_legacy_voices_file(
        voices_config_path=settings.voices_config_path,
    )
    print(json.dumps({"migrated_count": len(created), "items": created}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
