from typing import Any

from backend.app.inference.types import CancelChecker, PreparedSynthesisRequest, ProgressCallback
from backend.app.schemas.tts import SpeechRequest
from backend.app.schemas.voice import VoiceProfile
from backend.app.schemas.model_catalog import ModelRecord, PresetRecord


class TtsService:
    def prepare_request(self, request: SpeechRequest, voice: VoiceProfile) -> PreparedSynthesisRequest:
        defaults = voice.defaults
        return PreparedSynthesisRequest(
            input_text=request.input,
            voice_name=voice.name,
            model=request.model,
            response_format=request.response_format,
            text_lang=request.text_lang,
            text_split_method=request.text_split_method,
            chunk_length=request.chunk_length,
            history_window=request.history_window,
            speed=request.speed if request.speed is not None else defaults.speed,
            top_k=request.top_k if request.top_k is not None else defaults.top_k,
            top_p=request.top_p if request.top_p is not None else defaults.top_p,
            temperature=request.temperature if request.temperature is not None else defaults.temperature,
            pause_length=request.pause_length if request.pause_length is not None else defaults.pause_length,
            noise_scale=request.noise_scale if request.noise_scale is not None else 0.35,
            ref_audio=request.ref_audio or voice.ref_audio,
            ref_text=request.ref_text or voice.ref_text,
            ref_lang=request.ref_lang or voice.ref_lang,
            gpt_path=voice.gpt_path,
            sovits_path=voice.sovits_path,
            model_id=request.model_id,
            model_revision=request.model_revision,
            preset_id=request.preset_id or request.voice,
            preset_revision=request.preset_revision,
            style_ref_audio=request.style_ref_audio,
            style_ref_text=request.style_ref_text,
            style_ref_lang=request.style_ref_lang,
        )

    def prepare_catalog_request(self, request: SpeechRequest, model: ModelRecord, preset: PresetRecord) -> PreparedSynthesisRequest:
        defaults = preset.defaults
        return PreparedSynthesisRequest(
            input_text=request.input, voice_name=request.voice, model=request.model,
            response_format=request.response_format, text_lang=request.text_lang,
            text_split_method=request.text_split_method, chunk_length=request.chunk_length,
            history_window=request.history_window,
            speed=request.speed if request.speed is not None else float(defaults.get("speed", 1.0)),
            top_k=request.top_k if request.top_k is not None else int(defaults.get("top_k", 15)),
            top_p=request.top_p if request.top_p is not None else float(defaults.get("top_p", 1.0)),
            temperature=request.temperature if request.temperature is not None else float(defaults.get("temperature", 1.0)),
            pause_length=request.pause_length if request.pause_length is not None else float(defaults.get("pause_length", 0.3)),
            noise_scale=request.noise_scale if request.noise_scale is not None else float(defaults.get("noise_scale", 0.35)),
            ref_audio=request.ref_audio or preset.speaker_reference_audio_path,
            ref_text=request.ref_text or preset.speaker_reference_text,
            ref_lang=request.ref_lang or preset.speaker_reference_language,
            gpt_path=model.gpt_path_hint, sovits_path=model.sovits_path_hint,
            model_id=model.model_id, model_revision=model.model_revision,
            preset_id=preset.preset_id, preset_revision=preset.preset_revision,
            style_ref_audio=request.style_ref_audio or preset.style_reference_audio_path,
            style_ref_text=request.style_ref_text or preset.style_reference_text,
            style_ref_lang=request.style_ref_lang or preset.style_reference_language,
        )

    def synthesize_stream(
        self,
        request: SpeechRequest,
        voice: VoiceProfile,
        inference_engine: Any,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ):
        prepared_request = self.prepare_request(request=request, voice=voice)
        return self.synthesize_prepared_stream(
            prepared_request=prepared_request,
            inference_engine=inference_engine,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    def synthesize_prepared_stream(
        self,
        prepared_request: PreparedSynthesisRequest,
        inference_engine: Any,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ):
        if prepared_request.response_format not in {"wav", "mp3"}:
            raise ValueError(f"Unsupported response_format '{prepared_request.response_format}'.")
        return inference_engine.synthesize_stream(
            prepared_request,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
