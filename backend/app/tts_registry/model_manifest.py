from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.app.inference.adapter_definition import AdapterDefinition, OverridePolicy
from backend.app.inference.asset_fingerprint import fingerprint_file
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.editable_types import fingerprint_inference_config
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore
from backend.app.tts_registry.types import ModelInstance, ModelPreset, ModelSourceType


MODEL_MANIFEST_FILENAME = "neo-tts-model.json"
_WEIGHT_FILE_SUFFIXES = {".ckpt", ".onnx", ".pth"}
_SCHEMA_TYPE_MAPPING: dict[str, type | tuple[type, ...]] = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": dict,
    "string": str,
}


class ParsedModelManifest(BaseModel):
    schema_version: int = Field(description="manifest schema 版本。")
    package_id: str = Field(description="模型包 ID。")
    display_name: str = Field(description="模型包展示名。")
    adapter_id: str = Field(description="目标 adapter ID。")
    source_type: ModelSourceType = Field(description="模型包来源类型。")
    package_root: Path = Field(description="模型包根目录。")
    manifest_path: Path = Field(description="manifest 路径。")
    manifest_payload: dict[str, Any] = Field(default_factory=dict, description="原始 manifest 内容。")
    model_instance: ModelInstance = Field(description="解析后的模型实例。")
    fingerprint: str = Field(description="模型包稳定指纹。")


def load_model_manifest_from_package(
    package_root: str | Path,
    adapter_store: AdapterDefinitionStore,
) -> ParsedModelManifest:
    package_root = Path(package_root).resolve()
    manifest_path = package_root / MODEL_MANIFEST_FILENAME
    manifest_payload = _load_manifest_payload(package_root=package_root, manifest_path=manifest_path)
    adapter_id = str(manifest_payload.get("adapter_id") or "")
    adapter_definition = adapter_store.require(adapter_id)

    _validate_schema(payload=manifest_payload, schema=adapter_definition.manifest_schema, field_path="manifest")
    _validate_asset_topology(manifest_payload=manifest_payload, adapter_definition=adapter_definition)

    model_instance = _build_model_instance(
        package_root=package_root,
        manifest_payload=manifest_payload,
        adapter_definition=adapter_definition,
    )
    return ParsedModelManifest(
        schema_version=int(manifest_payload["schema_version"]),
        package_id=str(manifest_payload["package_id"]),
        display_name=str(manifest_payload["display_name"]),
        adapter_id=adapter_id,
        source_type=manifest_payload["source_type"],
        package_root=package_root,
        manifest_path=manifest_path,
        manifest_payload=manifest_payload,
        model_instance=model_instance,
        fingerprint=model_instance.fingerprint,
    )


def _load_manifest_payload(*, package_root: Path, manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        weight_files = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file() and path.suffix.lower() in _WEIGHT_FILE_SUFFIXES
        )
        raise BlockAdapterError(
            error_code="manifest_missing",
            message=f"缺少 {MODEL_MANIFEST_FILENAME}，模型包无法注册。",
            details={
                "manifest_name": MODEL_MANIFEST_FILENAME,
                "package_root": package_root.as_posix(),
                "detected_weight_files": weight_files,
            },
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BlockAdapterError(
            error_code="manifest_schema_invalid",
            message=f"{MODEL_MANIFEST_FILENAME} 不是合法 JSON。",
            details={"field": "manifest", "reason": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise BlockAdapterError(
            error_code="manifest_schema_invalid",
            message="模型包 manifest 顶层必须是 object。",
            details={"field": "manifest", "reason": "top_level_not_object"},
        )
    return payload


def _validate_schema(*, payload: Any, schema: dict[str, Any], field_path: str) -> None:
    if not schema:
        return

    schema_type = schema.get("type")
    if schema_type:
        expected_type = _SCHEMA_TYPE_MAPPING.get(schema_type)
        if expected_type is None:
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"暂不支持的 schema type: {schema_type}",
                details={"field": field_path, "schema_type": schema_type},
            )
        if not isinstance(payload, expected_type):
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"{field_path} 类型不符合 adapter manifest schema。",
                details={"field": field_path, "expected_type": schema_type},
            )

    if isinstance(payload, dict):
        for required_field in schema.get("required", []):
            if required_field not in payload:
                raise BlockAdapterError(
                    error_code="manifest_schema_invalid",
                    message=f"manifest 缺少必填字段 {required_field}。",
                    details={"field": f"{field_path}.{required_field}"},
                )
        for property_name, property_schema in schema.get("properties", {}).items():
            if property_name in payload:
                _validate_schema(
                    payload=payload[property_name],
                    schema=property_schema,
                    field_path=f"{field_path}.{property_name}",
                )
        return

    if isinstance(payload, list) and "items" in schema:
        for index, item in enumerate(payload):
            _validate_schema(payload=item, schema=schema["items"], field_path=f"{field_path}[{index}]")


def _validate_asset_topology(*, manifest_payload: dict[str, Any], adapter_definition: AdapterDefinition) -> None:
    instance_assets = _read_asset_mapping(manifest_payload.get("instance", {}), field_path="instance")
    _validate_asset_keys(
        asset_mapping=instance_assets,
        allowed_keys=set(adapter_definition.asset_topology.instance_assets),
        field_path="instance.assets",
    )
    for index, preset_payload in enumerate(manifest_payload.get("presets", [])):
        _validate_schema(
            payload=preset_payload,
            schema=adapter_definition.preset_schema,
            field_path=f"presets[{index}]",
        )
        preset_assets = _read_asset_mapping(preset_payload, field_path=f"presets[{index}]")
        _validate_asset_keys(
            asset_mapping=preset_assets,
            allowed_keys=set(adapter_definition.asset_topology.preset_assets),
            field_path=f"presets[{index}].assets",
        )


def _validate_asset_keys(*, asset_mapping: dict[str, str], allowed_keys: set[str], field_path: str) -> None:
    for asset_key in asset_mapping:
        if asset_key not in allowed_keys:
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"{field_path} 包含未声明的资产键 {asset_key}。",
                details={"field": field_path, "asset_key": asset_key},
            )


def _read_asset_mapping(owner_payload: dict[str, Any], *, field_path: str) -> dict[str, str]:
    assets = owner_payload.get("assets", {})
    if assets is None:
        return {}
    if not isinstance(assets, dict):
        raise BlockAdapterError(
            error_code="manifest_schema_invalid",
            message=f"{field_path}.assets 必须是 object。",
            details={"field": f"{field_path}.assets"},
        )
    result: dict[str, str] = {}
    for asset_key, raw_path in assets.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"{field_path}.assets.{asset_key} 必须是非空字符串路径。",
                details={"field": f"{field_path}.assets.{asset_key}", "asset_key": asset_key},
            )
        result[str(asset_key)] = raw_path
    return result


def _build_model_instance(
    *,
    package_root: Path,
    manifest_payload: dict[str, Any],
    adapter_definition: AdapterDefinition,
) -> ModelInstance:
    source_type = manifest_payload["source_type"]
    instance_payload = manifest_payload.get("instance", {})
    instance_assets = _resolve_assets(
        package_root=package_root,
        asset_mapping=_read_asset_mapping(instance_payload, field_path="instance"),
    )
    endpoint = _build_endpoint(instance_payload)
    account_binding = _build_account_binding(instance_payload)
    presets = [
        _build_model_preset(
            package_root=package_root,
            preset_payload=preset_payload,
            source_type=source_type,
            adapter_definition=adapter_definition,
        )
        for preset_payload in manifest_payload.get("presets", [])
    ]
    fingerprint = _build_instance_fingerprint(
        model_instance_id=str(manifest_payload["package_id"]),
        adapter_id=str(manifest_payload["adapter_id"]),
        source_type=source_type,
        display_name=str(manifest_payload["display_name"]),
        storage_mode=str(manifest_payload.get("storage_mode") or "managed"),
        status=_resolve_instance_status(source_type=source_type, instance_payload=instance_payload),
        instance_assets=instance_assets,
        endpoint=endpoint,
        account_binding=account_binding,
        presets=presets,
    )
    return ModelInstance(
        model_instance_id=str(manifest_payload["package_id"]),
        adapter_id=str(manifest_payload["adapter_id"]),
        source_type=source_type,
        display_name=str(manifest_payload["display_name"]),
        status=_resolve_instance_status(source_type=source_type, instance_payload=instance_payload),
        storage_mode=str(manifest_payload.get("storage_mode") or "managed"),
        instance_assets=instance_assets,
        endpoint=endpoint,
        account_binding=account_binding,
        presets=presets,
        fingerprint=fingerprint,
    )


def _build_model_preset(
    *,
    package_root: Path,
    preset_payload: dict[str, Any],
    source_type: str,
    adapter_definition: AdapterDefinition,
) -> ModelPreset:
    preset_assets = _resolve_assets(
        package_root=package_root,
        asset_mapping=_read_asset_mapping(preset_payload, field_path=f"preset:{preset_payload.get('preset_id', '')}"),
    )
    preset_kind = _resolve_preset_kind(source_type=source_type, preset_payload=preset_payload)
    fingerprint = _build_preset_fingerprint(
        preset_id=str(preset_payload["preset_id"]),
        display_name=str(preset_payload["display_name"]),
        kind=preset_kind,
        status=str(preset_payload.get("status") or "ready"),
        base_preset_id=preset_payload.get("base_preset_id"),
        fixed_fields=preset_payload.get("fixed_fields", {}),
        defaults=preset_payload.get("defaults", {}),
        preset_assets=preset_assets,
        override_policy=adapter_definition.override_policy,
    )
    return ModelPreset(
        preset_id=str(preset_payload["preset_id"]),
        display_name=str(preset_payload["display_name"]),
        kind=preset_kind,
        status=str(preset_payload.get("status") or "ready"),
        base_preset_id=preset_payload.get("base_preset_id"),
        fixed_fields=_ensure_object(preset_payload.get("fixed_fields", {}), field_path="preset.fixed_fields"),
        defaults=_ensure_object(preset_payload.get("defaults", {}), field_path="preset.defaults"),
        preset_assets=preset_assets,
        override_policy=adapter_definition.override_policy,
        fingerprint=fingerprint,
    )


def _resolve_assets(*, package_root: Path, asset_mapping: dict[str, str]) -> dict[str, dict[str, str]]:
    resolved_assets: dict[str, dict[str, str]] = {}
    for asset_key, raw_path in asset_mapping.items():
        relative_path = Path(raw_path)
        if relative_path.is_absolute():
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"资产 {asset_key} 必须使用包内相对路径。",
                details={"field": asset_key, "asset_key": asset_key, "path": raw_path},
            )
        resolved_path = (package_root / relative_path).resolve()
        try:
            resolved_path.relative_to(package_root)
        except ValueError as exc:
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message=f"资产 {asset_key} 超出模型包根目录。",
                details={"field": asset_key, "asset_key": asset_key, "path": raw_path},
            ) from exc
        if not resolved_path.exists():
            raise BlockAdapterError(
                error_code="asset_missing",
                message=f"模型包缺少资产 {asset_key}。",
                details={"asset_key": asset_key, "path": relative_path.as_posix()},
            )
        resolved_assets[asset_key] = {
            "relative_path": relative_path.as_posix(),
            "source_path": resolved_path.as_posix(),
            "fingerprint": _fingerprint_path(resolved_path),
        }
    return resolved_assets


def _fingerprint_path(path: Path) -> str:
    if path.is_file():
        return fingerprint_file(path)

    entries: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            stat = child.stat()
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return fingerprint_inference_config({"directory": path.name, "entries": entries})


def _build_endpoint(instance_payload: dict[str, Any]) -> dict[str, Any] | None:
    endpoint_url = instance_payload.get("endpoint_url")
    if not endpoint_url:
        return None
    endpoint: dict[str, Any] = {"url": endpoint_url}
    provider = instance_payload.get("provider")
    if provider:
        endpoint["provider"] = str(provider)
    return endpoint


def _build_account_binding(instance_payload: dict[str, Any]) -> dict[str, Any] | None:
    account_binding = _ensure_object(instance_payload.get("account_binding", {}), field_path="instance.account_binding")
    auth_payload = instance_payload.get("auth")
    if auth_payload is not None:
        auth_mapping = _ensure_object(auth_payload, field_path="instance.auth")
        required_secrets = auth_mapping.get("required_secrets") or []
        if not isinstance(required_secrets, list):
            raise BlockAdapterError(
                error_code="manifest_schema_invalid",
                message="instance.auth.required_secrets 必须是数组。",
                details={"field": "instance.auth.required_secrets"},
            )
        if required_secrets:
            account_binding["required_secrets"] = [str(item) for item in required_secrets]
            account_binding.setdefault("secret_handles", {})
    return account_binding or None


def _resolve_instance_status(*, source_type: str, instance_payload: dict[str, Any]) -> str:
    if source_type == "external_api":
        auth_payload = instance_payload.get("auth")
        if isinstance(auth_payload, dict) and auth_payload.get("required_secrets"):
            return "needs_secret"
    return str(instance_payload.get("status") or "ready")


def _resolve_preset_kind(*, source_type: str, preset_payload: dict[str, Any]) -> str:
    explicit_kind = preset_payload.get("kind")
    if explicit_kind:
        return str(explicit_kind)
    if source_type == "builtin":
        return "builtin"
    if source_type == "external_api":
        return "remote"
    return "imported"


def _build_preset_fingerprint(
    *,
    preset_id: str,
    display_name: str,
    kind: str,
    status: str,
    base_preset_id: str | None,
    fixed_fields: dict[str, Any],
    defaults: dict[str, Any],
    preset_assets: dict[str, dict[str, str]],
    override_policy: OverridePolicy,
) -> str:
    return fingerprint_inference_config(
        {
            "preset_id": preset_id,
            "display_name": display_name,
            "kind": kind,
            "status": status,
            "base_preset_id": base_preset_id,
            "fixed_fields": fixed_fields,
            "defaults": defaults,
            "preset_assets": _stable_asset_payload(preset_assets),
            "override_policy": override_policy.model_dump(mode="json"),
        }
    )


def _build_instance_fingerprint(
    *,
    model_instance_id: str,
    adapter_id: str,
    source_type: str,
    display_name: str,
    storage_mode: str,
    status: str,
    instance_assets: dict[str, dict[str, str]],
    endpoint: dict[str, Any] | None,
    account_binding: dict[str, Any] | None,
    presets: list[ModelPreset],
) -> str:
    return fingerprint_inference_config(
        {
            "model_instance_id": model_instance_id,
            "adapter_id": adapter_id,
            "source_type": source_type,
            "display_name": display_name,
            "storage_mode": storage_mode,
            "status": status,
            "instance_assets": _stable_asset_payload(instance_assets),
            "endpoint": endpoint,
            "account_binding": account_binding,
            "presets": [preset.model_dump(mode="json") for preset in presets],
        }
    )


def _stable_asset_payload(asset_payload: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        asset_key: {
            "relative_path": value["relative_path"],
            "fingerprint": value["fingerprint"],
        }
        for asset_key, value in sorted(asset_payload.items())
    }


def _ensure_object(value: Any, *, field_path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BlockAdapterError(
            error_code="manifest_schema_invalid",
            message=f"{field_path} 必须是 object。",
            details={"field": field_path},
        )
    return value
