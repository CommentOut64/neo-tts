from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile


class VoiceService:
    def __init__(self, repository: VoiceRepository) -> None:
        self._repository = repository

    def list_voices(self) -> list[VoiceProfile]:
        return [VoiceProfile.model_validate(item) for item in self._repository.list_voices()]

    def get_voice(self, voice_name: str) -> VoiceProfile:
        return VoiceProfile.model_validate(self._repository.get_voice(voice_name))

    def reload_voices(self) -> int:
        return len(self._repository.reload())

    def create_uploaded_voice(
        self,
        *,
        name: str,
        description: str,
        ref_text: str,
        ref_lang: str,
        defaults: VoiceDefaults,
        gpt_filename: str,
        gpt_bytes: bytes,
        sovits_filename: str,
        sovits_bytes: bytes,
        ref_audio_filename: str,
        ref_audio_bytes: bytes,
    ) -> VoiceProfile:
        created = self._repository.create_uploaded_voice(
            name=name,
            description=description,
            ref_text=ref_text,
            ref_lang=ref_lang,
            defaults=defaults,
            gpt_filename=gpt_filename,
            gpt_bytes=gpt_bytes,
            sovits_filename=sovits_filename,
            sovits_bytes=sovits_bytes,
            ref_audio_filename=ref_audio_filename,
            ref_audio_bytes=ref_audio_bytes,
        )
        return VoiceProfile.model_validate(created)

    def update_managed_voice(
        self,
        *,
        voice_name: str,
        description: str | None = None,
        ref_text: str | None = None,
        ref_lang: str | None = None,
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
            ref_text=ref_text,
            ref_lang=ref_lang,
            gpt_filename=gpt_filename,
            gpt_bytes=gpt_bytes,
            sovits_filename=sovits_filename,
            sovits_bytes=sovits_bytes,
            ref_audio_filename=ref_audio_filename,
            ref_audio_bytes=ref_audio_bytes,
        )
        return VoiceProfile.model_validate(updated)

    def delete_voice(self, voice_name: str) -> None:
        self._repository.delete_voice(voice_name)
