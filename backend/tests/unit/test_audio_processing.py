import io
import wave

import numpy as np

from backend.app.inference.audio_processing import (
    build_wav_bytes,
    build_wav_header,
    float_audio_chunk_to_pcm16_bytes,
)


def test_build_wav_header_contains_valid_mono_pcm_settings():
    header = build_wav_header(sample_rate=32000)
    with wave.open(io.BytesIO(header), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 32000
        assert wav_file.getnframes() == 0


def test_float_audio_chunk_to_pcm16_bytes_clips_out_of_range_values():
    samples = np.array([-2.0, -1.0, 0.0, 1.0, 2.0], dtype=np.float32)

    chunk = float_audio_chunk_to_pcm16_bytes(samples)
    restored = np.frombuffer(chunk, dtype=np.int16)

    assert restored[0] == -32767
    assert restored[1] == -32767
    assert restored[2] == 0
    assert restored[3] == 32767
    assert restored[4] == 32767


def test_build_wav_bytes_writes_correct_frame_count():
    pcm = float_audio_chunk_to_pcm16_bytes(np.array([0.2, -0.2, 0.0], dtype=np.float32))

    wav_bytes = build_wav_bytes(sample_rate=32000, pcm16_payload=pcm)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 32000
        assert wav_file.getnframes() == 3
