from backend.app.inference.editable_types import fingerprint_inference_config
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.types import ModelInstance, ModelPreset


class VoiceService:
    def __init__(self, repository: VoiceRepository, model_registry: ModelRegistry | None = None) -> None:
        self._repository = repository
        self._model_registry = model_registry

    def list_voices(self) -> list[VoiceProfile]:
        if self._model_registry is None:
            return [VoiceProfile.model_validate(item) for item in self._repository.list_voices()]
        return self.project_registry_voices(self._ensure_registry_models())

    def get_voice(self, voice_name: str) -> VoiceProfile:
        if self._model_registry is None:
            return VoiceProfile.model_validate(self._repository.get_voice(voice_name))
        return self.get_projected_registry_voice(self._ensure_registry_models(), voice_name)

    def get_voice_profile(self, voice_name: str) -> VoiceProfile:
        return self.get_voice(voice_name)

    def reload_voices(self) -> int:
        if self._model_registry is None:
            return len(self._repository.reload())
        self._model_registry.reload()
        return len(self.project_registry_voices(self._ensure_registry_models()))

    def create_uploaded_voice(
        self,
        *,
        name: str,
        description: str,
        copy_weights_into_project: bool = True,
        ref_text: str,
        ref_lang: str,
        defaults: VoiceDefaults,
        gpt_external_path: str | None = None,
        sovits_external_path: str | None = None,
        gpt_filename: str | None = None,
        gpt_bytes: bytes | None = None,
        sovits_filename: str | None = None,
        sovits_bytes: bytes | None = None,
        ref_audio_filename: str,
        ref_audio_bytes: bytes,
    ) -> VoiceProfile:
        created = self._repository.create_uploaded_voice(
            name=name,
            description=description,
            copy_weights_into_project=copy_weights_into_project,
            ref_text=ref_text,
            ref_lang=ref_lang,
            defaults=defaults,
            gpt_external_path=gpt_external_path,
            sovits_external_path=sovits_external_path,
            gpt_filename=gpt_filename,
            gpt_bytes=gpt_bytes,
            sovits_filename=sovits_filename,
            sovits_bytes=sovits_bytes,
            ref_audio_filename=ref_audio_filename,
            ref_audio_bytes=ref_audio_bytes,
        )
        profile = VoiceProfile.model_validate(created)
        self._upsert_registry_projection(profile)
        return profile

    def update_managed_voice(
        self,
        *,
        voice_name: str,
        description: str | None = None,
        copy_weights_into_project: bool | None = None,
        ref_text: str | None = None,
        ref_lang: str | None = None,
        gpt_external_path: str | None = None,
        sovits_external_path: str | None = None,
        gpt_filename: str | None = None,
        gpt_bytes: bytes | None = None,
        sovits_filename: str | None = None,
        sovits_bytes: bytes | None = None,
        ref_audio_filename: str | None = None,
        ref_audio_bytes: bytes | None = None,
    ) -> VoiceProfile:
        updated = self._repository.update_managed_voice(
            voice_name=voice_name,
            description=description,
            copy_weights_into_project=copy_weights_into_project,
            ref_text=ref_text,
            ref_lang=ref_lang,
            gpt_external_path=gpt_external_path,
            sovits_external_path=sovits_external_path,
            gpt_filename=gpt_filename,
            gpt_bytes=gpt_bytes,
            sovits_filename=sovits_filename,
            sovits_bytes=sovits_bytes,
            ref_audio_filename=ref_audio_filename,
            ref_audio_bytes=ref_audio_bytes,
        )
        profile = VoiceProfile.model_validate(updated)
        self._upsert_registry_projection(profile)
        return profile

    def delete_voice(self, voice_name: str) -> None:
        self._repository.delete_voice(voice_name)
        if self._model_registry is None:
            return
        existing_model = self._model_registry.get_model(voice_name)
        if existing_model is not None and self._is_legacy_projection(existing_model):
            self._model_registry.delete_model(voice_name)

    @staticmethod
    def project_registry_voices(models: list[ModelInstance]) -> list[VoiceProfile]:
        projected: list[VoiceProfile] = []
        for model in models:
            if model.adapter_id != "gpt_sovits_local":
                continue
            for preset in model.presets:
                gpt_asset = preset.preset_assets.get("gpt_weight")
                sovits_asset = preset.preset_assets.get("sovits_weight")
                reference_asset = preset.preset_assets.get("reference_audio")
                if not isinstance(gpt_asset, dict) or not isinstance(sovits_asset, dict) or not isinstance(reference_asset, dict):
                    continue
                voice_name = model.model_instance_id if preset.preset_id == "default" else f"{model.model_instance_id}__{preset.preset_id}"
                defaults = VoiceDefaults.model_validate(
                    {
                        "speed": preset.defaults.get("speed", 1.0),
                        "top_k": preset.defaults.get("top_k", 15),
                        "top_p": preset.defaults.get("top_p", 1.0),
                        "temperature": preset.defaults.get("temperature", 1.0),
                        "noise_scale": preset.defaults.get("noise_scale", 0.35),
                        "pause_length": preset.defaults.get("pause_length", 0.3),
                    }
                )
                projected.append(
                    VoiceProfile(
                        name=voice_name,
                        model_instance_id=model.model_instance_id,
                        preset_id=preset.preset_id,
                        gpt_path=str(gpt_asset.get("source_path") or gpt_asset.get("relative_path") or ""),
                        sovits_path=str(sovits_asset.get("source_path") or sovits_asset.get("relative_path") or ""),
                        weight_storage_mode=model.storage_mode,
                        gpt_fingerprint=str(gpt_asset.get("fingerprint") or ""),
                        sovits_fingerprint=str(sovits_asset.get("fingerprint") or ""),
                        ref_audio=str(reference_asset.get("source_path") or reference_asset.get("relative_path") or ""),
                        ref_text=str(preset.defaults.get("reference_text") or ""),
                        ref_lang=str(preset.defaults.get("reference_language") or "zh"),
                        description=preset.display_name,
                        defaults=defaults,
                        managed=model.storage_mode == "managed",
                    )
                )
        projected.sort(key=lambda item: item.name)
        return projected

    @staticmethod
    def get_projected_registry_voice(models: list[ModelInstance], voice_name: str) -> VoiceProfile:
        for voice in VoiceService.project_registry_voices(models):
            if voice.name == voice_name:
                return voice
        raise LookupError(f"Voice '{voice_name}' not found.")

    def _ensure_registry_models(self) -> list[ModelInstance]:
        assert self._model_registry is not None
        legacy_profiles = [VoiceProfile.model_validate(item) for item in self._repository.list_voices()]
        for profile in legacy_profiles:
            existing_model = self._model_registry.get_model(profile.name)
            desired_model = self._build_registry_model_from_voice(profile)
            if existing_model is None:
                self._model_registry.replace_model(desired_model)
                continue
            if self._is_legacy_projection(existing_model) and self._legacy_projection_changed(existing_model, desired_model):
                self._model_registry.replace_model(desired_model)
        return self._model_registry.list_models()

    def _upsert_registry_projection(self, profile: VoiceProfile) -> None:
        if self._model_registry is None:
            return
        existing_model = self._model_registry.get_model(profile.name)
        if existing_model is not None and not self._is_legacy_projection(existing_model):
            raise ValueError(f"Voice '{profile.name}' conflicts with existing registry model '{profile.name}'.")
        self._model_registry.replace_model(self._build_registry_model_from_voice(profile))

    @staticmethod
    def _build_registry_model_from_voice(profile: VoiceProfile) -> ModelInstance:
        override_policy = build_default_adapter_definition_store().require("gpt_sovits_local").override_policy
        preset = ModelPreset(
            preset_id="default",
            display_name=profile.description,
            kind="user" if profile.managed else "imported",
            status="ready",
            base_preset_id=None,
            fixed_fields={},
            defaults={
                "reference_text": profile.ref_text,
                "reference_language": profile.ref_lang,
                "speed": profile.defaults.speed,
                "top_k": profile.defaults.top_k,
                "top_p": profile.defaults.top_p,
                "temperature": profile.defaults.temperature,
                "noise_scale": profile.defaults.noise_scale,
                "pause_length": profile.defaults.pause_length,
            },
            preset_assets={
                "gpt_weight": VoiceService._build_asset_payload(
                    path=profile.gpt_path,
                    fingerprint=profile.gpt_fingerprint,
                ),
                "sovits_weight": VoiceService._build_asset_payload(
                    path=profile.sovits_path,
                    fingerprint=profile.sovits_fingerprint,
                ),
                "reference_audio": VoiceService._build_asset_payload(
                    path=profile.ref_audio,
                    fingerprint="",
                ),
            },
            override_policy=override_policy,
            fingerprint=VoiceService._build_preset_fingerprint(profile),
        )
        return ModelInstance(
            model_instance_id=profile.name,
            adapter_id="gpt_sovits_local",
            source_type="local_package",
            display_name=profile.description or profile.name,
            status="ready",
            storage_mode=profile.weight_storage_mode,
            instance_assets={
                "legacy_voice_profile": {
                    "voice_name": profile.name,
                    "managed": profile.managed,
                }
            },
            endpoint=None,
            account_binding=None,
            adapter_options={},
            presets=[preset],
            fingerprint="pending",
        )

    @staticmethod
    def _build_asset_payload(*, path: str, fingerprint: str) -> dict[str, str]:
        return {
            "relative_path": path,
            "source_path": path,
            "fingerprint": fingerprint,
        }

    @staticmethod
    def _build_preset_fingerprint(profile: VoiceProfile) -> str:
        return fingerprint_inference_config(
            {
                "preset_id": "default",
                "display_name": profile.description,
                "kind": "user" if profile.managed else "imported",
                "status": "ready",
                "defaults": {
                    "reference_text": profile.ref_text,
                    "reference_language": profile.ref_lang,
                    "speed": profile.defaults.speed,
                    "top_k": profile.defaults.top_k,
                    "top_p": profile.defaults.top_p,
                    "temperature": profile.defaults.temperature,
                    "noise_scale": profile.defaults.noise_scale,
                    "pause_length": profile.defaults.pause_length,
                },
                "preset_assets": {
                    "gpt_weight": {
                        "relative_path": profile.gpt_path,
                        "fingerprint": profile.gpt_fingerprint,
                    },
                    "sovits_weight": {
                        "relative_path": profile.sovits_path,
                        "fingerprint": profile.sovits_fingerprint,
                    },
                    "reference_audio": {
                        "relative_path": profile.ref_audio,
                        "fingerprint": "",
                    },
                },
            }
        )

    @staticmethod
    def _is_legacy_projection(model: ModelInstance) -> bool:
        legacy_marker = model.instance_assets.get("legacy_voice_profile")
        return isinstance(legacy_marker, dict)

    @staticmethod
    def _legacy_projection_changed(existing_model: ModelInstance, desired_model: ModelInstance) -> bool:
        existing_payload = existing_model.model_dump(mode="json")
        desired_payload = desired_model.model_dump(mode="json")
        existing_payload.pop("fingerprint", None)
        desired_payload.pop("fingerprint", None)
        return existing_payload != desired_payload
