import torch

from GPT_SoVITS.module.models import SynthesizerTrn


class _FakeQuantizer:
    def decode(self, codes: torch.Tensor) -> torch.Tensor:
        batch_size, _, semantic_length = codes.shape
        return torch.ones((batch_size, 768, semantic_length), dtype=torch.float32)


class _RecordingEncoder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(
        self,
        quantized: torch.Tensor,
        y_lengths: torch.Tensor,
        text: torch.Tensor,
        text_lengths: torch.Tensor,
        ge,
        speed: float = 1,
        test=None,
        result_length: int | None = None,
        overlap_frames: torch.Tensor | None = None,
        padding_length: int | None = None,
    ):
        del text, text_lengths, ge, speed, test
        effective_length = int(result_length) if result_length is not None else int(quantized.shape[-1])
        self.calls.append(
            {
                "quantized_shape": list(quantized.shape),
                "y_lengths": y_lengths.detach().cpu().tolist(),
                "result_length": result_length,
                "padding_length": padding_length,
                "overlap_shape": None if overlap_frames is None else list(overlap_frames.shape),
            }
        )
        latent = torch.zeros((quantized.shape[0], 2, effective_length), dtype=torch.float32)
        y_mask = torch.ones((quantized.shape[0], 1, effective_length), dtype=torch.float32)
        return latent, torch.zeros_like(latent), torch.zeros_like(latent), y_mask, latent.clone(), y_mask.clone()


def _build_streaming_model(*, semantic_frame_rate: str = "25hz") -> tuple[SynthesizerTrn, _RecordingEncoder]:
    model = SynthesizerTrn.__new__(SynthesizerTrn)
    torch.nn.Module.__init__(model)
    model.version = "v2"
    model.is_v2pro = False
    model.semantic_frame_rate = semantic_frame_rate
    model.quantizer = _FakeQuantizer()
    encoder = _RecordingEncoder()
    model.enc_p = encoder
    model.flow = lambda z_p, y_mask, g=None, reverse=False: z_p
    model.dec = lambda z, g=None: z[:, :1, :]
    return model, encoder


def test_decode_streaming_keeps_requested_boundary_window_lengths_for_25hz():
    model, encoder = _build_streaming_model(semantic_frame_rate="25hz")

    model.decode_streaming(
        codes=torch.ones((1, 1, 8), dtype=torch.long),
        text=torch.ones((1, 5), dtype=torch.long),
        refer=None,
        result_length=6,
        overlap_frames=torch.zeros((1, 1, 6), dtype=torch.float32),
        padding_length=4,
    )

    assert encoder.calls[0]["quantized_shape"] == [1, 768, 16]
    assert encoder.calls[0]["y_lengths"] == [16]
    assert encoder.calls[0]["result_length"] == 6
    assert encoder.calls[0]["padding_length"] == 4


def test_decode_boundary_prefix_returns_requested_window_length_for_25hz():
    model, _ = _build_streaming_model(semantic_frame_rate="25hz")

    boundary_audio, boundary_frame_count, trace = model.decode_boundary_prefix(
        codes=torch.ones((1, 1, 8), dtype=torch.long),
        text=torch.ones((1, 5), dtype=torch.long),
        refer=None,
        left_overlap_frames=torch.zeros((1, 1, 6), dtype=torch.float32),
        boundary_overlap_frame_count=6,
        boundary_padding_frame_count=4,
        boundary_result_frame_count=6,
    )

    assert boundary_audio.shape[-1] == 6
    assert boundary_frame_count == 6
    assert trace["requested_result_frame_count"] == 6
