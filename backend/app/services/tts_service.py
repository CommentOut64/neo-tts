from typing import Any

from backend.app.inference.types import PreparedSynthesisRequest
from backend.app.schemas.tts import SpeechRequest
from backend.app.schemas.voice import VoiceProfile


class TtsService:
    def prepare_request(self, request: SpeechRequest, voice: VoiceProfile) -> PreparedSynthesisRequest:
        defaults = voice.defaults
        return PreparedSynthesisRequest(
            input_text=request.input,
            voice_name=voice.name,
            model=request.model,
            response_format=request.response_format,
            text_lang=request.text_lang,
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
        )

    def synthesize_stream(
        self,
        request: SpeechRequest,
        voice: VoiceProfile,
        inference_engine: Any,
    ):
        prepared_request = self.prepare_request(request=request, voice=voice)
        return self.synthesize_prepared_stream(prepared_request=prepared_request, inference_engine=inference_engine)

    def synthesize_prepared_stream(
        self,
        prepared_request: PreparedSynthesisRequest,
        inference_engine: Any,
    ):
        if prepared_request.response_format not in {"wav", "mp3"}:
            raise ValueError(f"Unsupported response_format '{prepared_request.response_format}'.")
        return inference_engine.synthesize_stream(prepared_request)
