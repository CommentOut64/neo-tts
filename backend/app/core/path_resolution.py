from __future__ import annotations

import os
from pathlib import Path


def resolve_runtime_path(
    raw_path: str | Path,
    *,
    project_root: Path | None = None,
    user_data_root: Path | None = None,
    resources_root: Path | None = None,
    managed_voices_dir: Path | None = None,
) -> Path:
    resolved_project_root, resolved_user_data_root, resolved_resources_root, resolved_managed_voices_dir = (
        _resolve_runtime_roots(
            project_root=project_root,
            user_data_root=user_data_root,
            resources_root=resources_root,
            managed_voices_dir=managed_voices_dir,
        )
    )

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()

    candidates = (
        (resolved_user_data_root / path).resolve(),
        (resolved_resources_root / path).resolve(),
        (resolved_project_root / path).resolve(),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate

    if path.parts and path.parts[0] == resolved_managed_voices_dir.name:
        return (resolved_managed_voices_dir.parent / path).resolve()
    return (resolved_project_root / path).resolve()


def _resolve_runtime_roots(
    *,
    project_root: Path | None,
    user_data_root: Path | None,
    resources_root: Path | None,
    managed_voices_dir: Path | None,
) -> tuple[Path, Path, Path, Path]:
    resolved_project_root = _resolve_optional_root(
        explicit=project_root,
        env_name="NEO_TTS_PROJECT_ROOT",
        default=Path(__file__).resolve().parents[3],
    )
    resolved_user_data_root = _resolve_optional_root(
        explicit=user_data_root,
        env_name="NEO_TTS_USER_DATA_ROOT",
        default=resolved_project_root / "storage",
    )
    resolved_resources_root = _resolve_optional_root(
        explicit=resources_root,
        env_name="NEO_TTS_RESOURCES_ROOT",
        default=resolved_project_root,
    )
    resolved_managed_voices_dir = _resolve_optional_root(
        explicit=managed_voices_dir,
        env_name="GPT_SOVITS_MANAGED_VOICES_DIR",
        default=resolved_user_data_root / "managed_voices",
    )
    return (
        resolved_project_root,
        resolved_user_data_root,
        resolved_resources_root,
        resolved_managed_voices_dir,
    )


def _resolve_optional_root(*, explicit: Path | None, env_name: str, default: Path) -> Path:
    if explicit is not None:
        return explicit.resolve()
    raw_value = os.environ.get(env_name)
    if raw_value:
        return Path(raw_value).resolve()
    return default.resolve()
