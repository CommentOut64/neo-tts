import numpy as np
import pytest
import torch


def test_prompt_cache_key_changes_when_reference_inputs_change():
    from backend.app.inference.prompt_cache import PromptCacheKey

    base_key = PromptCacheKey(
        reference_scope="voice_preset",
        reference_identity="voice-a:preset",
        reference_audio_path="ref.wav",
        reference_audio_fingerprint="audio-fp-1",
        reference_text="参考文本",
        reference_text_fingerprint="text-fp-1",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )

    changed_text_key = PromptCacheKey(
        reference_scope="voice_preset",
        reference_identity="voice-a:preset",
        reference_audio_path="ref.wav",
        reference_audio_fingerprint="audio-fp-1",
        reference_text="另一段参考文本",
        reference_text_fingerprint="text-fp-2",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )
    changed_audio_key = PromptCacheKey(
        reference_scope="voice_preset",
        reference_identity="voice-a:preset",
        reference_audio_path="ref-2.wav",
        reference_audio_fingerprint="audio-fp-2",
        reference_text="参考文本",
        reference_text_fingerprint="text-fp-1",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )
    changed_scope_key = PromptCacheKey(
        reference_scope="session_override",
        reference_identity="session-1:binding-a",
        reference_audio_path="ref.wav",
        reference_audio_fingerprint="audio-fp-1",
        reference_text="参考文本",
        reference_text_fingerprint="text-fp-1",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )

    assert base_key != changed_text_key
    assert base_key != changed_audio_key
    assert base_key != changed_scope_key


def test_prompt_cache_stores_cpu_payload_and_evicts_oldest_entry():
    from backend.app.inference.prompt_cache import PromptCache, PromptCacheEntry, PromptCacheKey

    cache = PromptCache(max_entries=1)
    first_key = PromptCacheKey(
        reference_scope="voice_preset",
        reference_identity="voice-a:preset",
        reference_audio_path="ref-1.wav",
        reference_audio_fingerprint="audio-fp-1",
        reference_text="参考文本一",
        reference_text_fingerprint="text-fp-1",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )
    second_key = PromptCacheKey(
        reference_scope="session_override",
        reference_identity="session-1:binding-a",
        reference_audio_path="ref-2.wav",
        reference_audio_fingerprint="audio-fp-2",
        reference_text="参考文本二",
        reference_text_fingerprint="text-fp-2",
        reference_language="zh",
        model_version="v2Pro",
        inference_config_fingerprint="fp-1",
    )
    first_entry = PromptCacheEntry(
        reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
        reference_spectrogram_cpu=torch.ones((1, 3, 3), dtype=torch.float32),
        reference_speaker_embedding_cpu=torch.ones((1, 4), dtype=torch.float32),
        prompt_phones=[11, 12],
        prompt_bert_cpu=torch.ones((1024, 2), dtype=torch.float32),
        prompt_norm_text="参考文本一。",
    )
    second_entry = PromptCacheEntry(
        reference_semantic_tokens=np.asarray([4, 5, 6], dtype=np.int64),
        reference_spectrogram_cpu=torch.zeros((1, 3, 3), dtype=torch.float32),
        reference_speaker_embedding_cpu=torch.zeros((1, 4), dtype=torch.float32),
        prompt_phones=[21, 22],
        prompt_bert_cpu=torch.zeros((1024, 2), dtype=torch.float32),
        prompt_norm_text="参考文本二。",
    )

    cache.put(first_key, first_entry)
    cached_first = cache.get(first_key)
    assert cached_first is not None
    assert cached_first.reference_spectrogram_cpu.device.type == "cpu"
    assert cached_first.reference_speaker_embedding_cpu.device.type == "cpu"
    assert cached_first.prompt_bert_cpu.device.type == "cpu"

    cache.put(second_key, second_entry)

    assert cache.get(first_key) is None
    cached_second = cache.get(second_key)
    assert cached_second is not None
    assert cached_second.prompt_norm_text == "参考文本二。"
