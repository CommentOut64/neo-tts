from backend.app.schemas.tts import SpeechRequest
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.tts_service import TtsService
import pytest


def test_prepare_request_merges_voice_defaults():
    service = TtsService()
    voice = VoiceProfile(
        name="demo",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="demo.wav",
        ref_text="reference text",
        ref_lang="en",
        defaults=VoiceDefaults(
            speed=1.25,
            top_k=20,
            top_p=0.8,
            temperature=0.7,
            pause_length=0.5,
        ),
    )
    request = SpeechRequest(input="hello world", voice="demo")

    prepared = service.prepare_request(request, voice)

    assert prepared.input_text == "hello world"
    assert prepared.voice_name == "demo"
    assert prepared.speed == 1.25
    assert prepared.top_k == 20
    assert prepared.top_p == 0.8
    assert prepared.temperature == 0.7
    assert prepared.pause_length == 0.5
    assert prepared.ref_audio == "demo.wav"
    assert prepared.ref_text == "reference text"
    assert prepared.ref_lang == "en"


def test_prepare_request_prefers_request_overrides():
    service = TtsService()
    voice = VoiceProfile(
        name="demo",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="demo.wav",
        ref_text="reference text",
        ref_lang="en",
    )
    request = SpeechRequest(
        input="hello world",
        voice="demo",
        speed=0.9,
        top_k=5,
        top_p=0.6,
        temperature=0.5,
        pause_length=0.1,
        noise_scale=0.4,
        ref_audio="override.wav",
        ref_text="override text",
        ref_lang="zh",
        text_lang="ja",
    )

    prepared = service.prepare_request(request, voice)

    assert prepared.speed == 0.9
    assert prepared.top_k == 5
    assert prepared.top_p == 0.6
    assert prepared.temperature == 0.5
    assert prepared.pause_length == 0.1
    assert prepared.noise_scale == 0.4
    assert prepared.ref_audio == "override.wav"
    assert prepared.ref_text == "override text"
    assert prepared.ref_lang == "zh"
    assert prepared.text_lang == "ja"


def test_synthesize_stream_merges_request_and_calls_engine():
    class FakeEngine:
        def __init__(self) -> None:
            self.last_request = None

        def synthesize_stream(self, request):
            self.last_request = request
            return 32000, iter(["chunk"])

    service = TtsService()
    voice = VoiceProfile(
        name="demo",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="demo.wav",
        ref_text="reference text",
        ref_lang="en",
        defaults=VoiceDefaults(speed=1.2, top_k=11, top_p=0.7, temperature=0.6, pause_length=0.2),
    )
    request = SpeechRequest(input="hello world", voice="demo")
    engine = FakeEngine()

    sample_rate, stream = service.synthesize_stream(request=request, voice=voice, inference_engine=engine)

    assert sample_rate == 32000
    assert list(stream) == ["chunk"]
    assert engine.last_request is not None
    assert engine.last_request.speed == 1.2
    assert engine.last_request.top_k == 11


def test_synthesize_stream_rejects_unsupported_response_format():
    class FakeEngine:
        def synthesize_stream(self, request):
            return 32000, iter([])

    service = TtsService()
    voice = VoiceProfile(
        name="demo",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="demo.wav",
        ref_text="reference text",
        ref_lang="en",
    )
    request = SpeechRequest(input="hello world", voice="demo", response_format="ogg")

    with pytest.raises(ValueError, match="Unsupported response_format 'ogg'"):
        service.synthesize_stream(request=request, voice=voice, inference_engine=FakeEngine())
