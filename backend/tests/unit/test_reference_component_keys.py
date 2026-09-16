from runtime.gsv import SpeakerFeatureKey, StyleSemanticKey, StyleTextKey


def test_reference_component_keys_are_runtime_contracts():
    speaker = SpeakerFeatureKey("audio-a", "sovits-a", "hubert-a", "sv-a", "spectrogram-a")
    assert speaker != SpeakerFeatureKey("audio-b", "sovits-a", "hubert-a", "sv-a", "spectrogram-a")
    assert speaker != SpeakerFeatureKey("audio-a", "sovits-a", "hubert-b", "sv-a", "spectrogram-a")

    semantic = StyleSemanticKey("style-a", "hubert-a", "quantizer-a")
    assert semantic != StyleSemanticKey("style-b", "hubert-a", "quantizer-a")

    text = StyleTextKey("text-a", "zh", "g2p-a", "bert-a")
    assert text != StyleTextKey("text-a", "en", "g2p-a", "bert-a")
