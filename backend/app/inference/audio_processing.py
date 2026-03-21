from __future__ import annotations

import io
import wave

import numpy as np


def build_wav_header(sample_rate: int) -> bytes:
    header = io.BytesIO()
    with wave.open(header, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"")
    return header.getvalue()


def build_wav_bytes(sample_rate: int, pcm16_payload: bytes) -> bytes:
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16_payload)
    return wav_buffer.getvalue()


def float_audio_chunk_to_pcm16_bytes(audio_data: np.ndarray) -> bytes:
    clipped = np.clip(audio_data, -1.0, 1.0)
    audio_int16 = (clipped * 32767).astype(np.int16)
    return audio_int16.tobytes()


def load_reference_spectrogram(
    filename: str,
    device: str,
    sampling_rate: int,
    filter_length: int,
    hop_length: int,
    win_length: int,
    is_half: bool,
):
    import torchaudio

    from GPT_SoVITS.module.mel_processing import spectrogram_torch
    from GPT_SoVITS.utils import load_audio_equivalent

    audio, source_sr = load_audio_equivalent(filename, device)
    if source_sr != sampling_rate:
        audio = torchaudio.transforms.Resample(source_sr, sampling_rate).to(device)(audio)
    if audio.shape[0] > 1:
        audio = audio.mean(0, keepdim=True)
    spec = spectrogram_torch(
        audio,
        filter_length,
        sampling_rate,
        hop_length,
        win_length,
        center=False,
    )
    if is_half:
        spec = spec.half()
    return spec, audio
