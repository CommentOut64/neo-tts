from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .errors import (
    RuntimeFailure,
    RuntimePhase,
    check_cancelled,
    error_info,
    runtime_checkpoint,
)
from .language import LanguageResolutionService
from .diagnostics import runtime_entrypoint


def _ensure_gpt_path() -> None:
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    gpt_root = str(Path(root) / "GPT_SoVITS")
    if gpt_root not in sys.path:
        sys.path.insert(0, gpt_root)


def _clean_text_features(text: str, language: str, version: str, tokenizer, bert_model, device: str, dtype, resolution=None, *, g2pw_factory=None):
    import torch

    from GPT_SoVITS.text import cleaned_text_to_sequence
    from GPT_SoVITS.text.cleaner import clean_text

    resolution = resolution or LanguageResolutionService().resolve(language, text)
    phones_all: list[int] = []
    bert_all = []
    norm_all: list[str] = []
    for span in resolution.spans:
        lang = span.language
        chunk = span.text
        if not chunk:
            continue
        if lang == "zh" and version != "v1" and g2pw_factory is not None:
            phones, word2ph, norm = clean_text(chunk, lang, version, pinyin_converter=g2pw_factory())
        else:
            phones, word2ph, norm = clean_text(chunk, lang, version)
        ids = cleaned_text_to_sequence(phones, version)
        if lang in {"zh", "yue"}:
            inputs = tokenizer(norm, return_tensors="pt")
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                hidden = bert_model(**inputs, output_hidden_states=True)["hidden_states"][-2][0].cpu()[1:-1]
            bert = torch.cat([hidden[index].repeat(word2ph[index], 1) for index in range(len(word2ph))], dim=0).T
        else:
            bert = torch.zeros((1024, len(ids)), dtype=dtype)
        phones_all.extend(ids)
        bert_all.append(bert)
        norm_all.append(norm)
    if not phones_all or not bert_all:
        raise ValueError("Text frontend produced no phones")
    return phones_all, torch.cat(bert_all, dim=1).to(dtype), "".join(norm_all)


@runtime_entrypoint(RuntimePhase.REFERENCE, "reference.decode", "REFERENCE_DECODE_FAILED")
def _load_audio(path: str, target_sr: int, device: str):
    import librosa
    import torch
    import torchaudio

    waveform, source_sr = librosa.load(path, sr=None, mono=False)
    if waveform.ndim == 1:
        waveform = waveform[None, :]
    audio = torch.from_numpy(np.asarray(waveform, dtype=np.float32)).to(device)
    if source_sr != target_sr:
        audio = torchaudio.transforms.Resample(source_sr, target_sr).to(device)(audio)
    if audio.shape[0] > 1:
        audio = audio.mean(0, keepdim=True)
    return audio


def _reference_spectrogram(audio, hps, device):
    from GPT_SoVITS.module.mel_processing import spectrogram_torch

    return spectrogram_torch(
        audio,
        hps.data.filter_length,
        hps.data.sampling_rate,
        hps.data.hop_length,
        hps.data.win_length,
        center=False,
    )


def _split_audio(audio: np.ndarray, encoder_frames, margin_frames: int, stride: int) -> dict[str, object]:
    count = int(encoder_frames.shape[-1])
    margin = min(max((count - 10) // 2, 0), margin_frames) if count > 0 else 0
    samples = margin * stride
    if margin == 0:
        return {"decoder_frame_count": count, "core_audio": audio, "left_margin_audio": np.zeros(0, np.float32), "right_margin_audio": np.zeros(0, np.float32), "left_margin_frames": [], "right_margin_frames": []}
    left = audio[:samples].astype(np.float32, copy=True)
    core = audio[samples:-samples].astype(np.float32, copy=True)
    right = audio[-samples:].astype(np.float32, copy=True)
    return {
        "decoder_frame_count": count,
        "core_audio": core,
        "left_margin_audio": left,
        "right_margin_audio": right,
        "left_margin_frames": encoder_frames[..., :margin].detach().cpu().float().squeeze(0).tolist(),
        "right_margin_frames": encoder_frames[..., -margin:].detach().cpu().float().squeeze(0).tolist(),
    }


class NativeInferenceBackend:
    def __init__(self, *, t2s_model, vq_model, hps, device: str, dtype, resources_root: str, cnhubert_path=None, bert_path=None):
        self.t2s_model = t2s_model
        self.vq_model = vq_model
        self.hps = hps
        self.device = device
        self.dtype = dtype
        self.sample_rate = int(hps.data.sampling_rate)
        self.resources_root = Path(resources_root)
        self.cnhubert_path = cnhubert_path
        self.bert_path = bert_path
        self._g2pw = None
        self._frontends_ready = False
        self._closed = False

    def _ensure_frontends(self) -> None:
        if self._frontends_ready:
            return
        _ensure_gpt_path()
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer

        from GPT_SoVITS.feature_extractor import cnhubert
        from GPT_SoVITS.sv import SV

        root = self.resources_root
        hubert_path = Path(self.cnhubert_path or root / "pretrained_models" / "chinese-hubert-base")
        bert_path = Path(self.bert_path or root / "pretrained_models" / "chinese-roberta-wwm-ext-large")
        sv_path = root / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt"
        for path in (hubert_path, bert_path, sv_path):
            if not path.exists():
                raise FileNotFoundError(str(path))
        with runtime_checkpoint(None, RuntimePhase.RESOURCE, "resources.cnhubert", "RESOURCE_INVALID"):
            self.ssl_model = cnhubert.CNHubert(base_path=str(hubert_path)).to(self.device).eval()
        with runtime_checkpoint(None, RuntimePhase.RESOURCE, "resources.bert", "RESOURCE_INVALID"):
            self.tokenizer = AutoTokenizer.from_pretrained(str(bert_path), local_files_only=True)
            self.bert_model = AutoModelForMaskedLM.from_pretrained(str(bert_path), local_files_only=True).to(self.device).eval()
        with runtime_checkpoint(None, RuntimePhase.RESOURCE, "resources.sv", "RESOURCE_INVALID"):
            self.sv_model = SV(self.device, self.dtype == torch.float16, model_path=str(sv_path))
        self._frontends_ready = True

    def _get_g2pw(self, control=None, observer=None):
        if self._g2pw is not None:
            return self._g2pw
        with runtime_checkpoint(observer, RuntimePhase.TEXT_FRONTEND, "resources.g2pw", "TEXT_FRONTEND_FAILED", control):
            _ensure_gpt_path()
            try:
                from text.g2pw import G2PWPinyin

                self._g2pw = G2PWPinyin(
                    model_dir=str(self.resources_root / "GPT_SoVITS" / "text" / "G2PWModel"),
                    model_source=str(self.bert_path or self.resources_root / "pretrained_models" / "chinese-roberta-wwm-ext-large"),
                    v_to_u=False,
                    neutral_tone_with_five=True,
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"] if self.device == "cuda" else ["CPUExecutionProvider"],
                    local_files_only=True,
                )
            except (FileNotFoundError, ImportError) as exc:
                raise RuntimeFailure(error_info(
                    "LANGUAGE_RESOURCE_MISSING", checkpoint="resources.g2pw",
                    message="Required Chinese pronunciation resources are missing.", control=control,
                ), exc) from exc
            except RuntimeError as exc:
                raise RuntimeFailure(error_info(
                    "ORT_PROVIDER_FAILED", checkpoint="resources.g2pw",
                    message="The Chinese pronunciation provider could not be initialized.", control=control,
                ), exc) from exc
        return self._g2pw

    def prepare_reference(self, request, control=None, observer=None):
        import torch

        check_cancelled(control, "reference.start", observer)
        with runtime_checkpoint(observer, RuntimePhase.RESOURCE, "resources.frontends", "RESOURCE_MISSING", control):
            self._ensure_frontends()
        check_cancelled(control, "reference.frontends", observer)
        audio = _load_audio(request.audio_path, self.sample_rate, self.device)
        with torch.no_grad(), runtime_checkpoint(observer, RuntimePhase.REFERENCE, "reference.features", "REFERENCE_FEATURE_FAILED", control):
            spec = _reference_spectrogram(audio, self.hps, self.device).to(dtype=self.dtype)
            wav16k = _load_audio(request.audio_path, 16000, self.device).flatten()
            wav16k = torch.cat([wav16k, torch.zeros(int(16000 * 0.3), device=self.device, dtype=wav16k.dtype)])
            ssl = self.ssl_model.model(wav16k.unsqueeze(0))["last_hidden_state"].transpose(1, 2).to(dtype=self.dtype)
            semantic = self.vq_model.extract_latent(ssl)[0, 0].detach().cpu().numpy()
            check_cancelled(control, "reference.semantic", observer)
            if self.sample_rate != 16000:
                audio16 = _load_audio(request.audio_path, 16000, self.device)
            else:
                audio16 = audio
            speaker = self.sv_model.compute_embedding3(audio16).detach().cpu()
        check_cancelled(control, "reference.speaker", observer)
        with runtime_checkpoint(observer, RuntimePhase.TEXT_FRONTEND, "reference.g2p", "TEXT_FRONTEND_FAILED", control):
            phones, bert, norm = _clean_text_features(
                request.text, request.language, self.hps.model.version, self.tokenizer,
                self.bert_model, self.device, self.dtype, request.language_resolution,
                g2pw_factory=lambda: self._get_g2pw(control, observer),
            )
        check_cancelled(control, "reference.output", observer)
        return {
            "semantic": semantic,
            "spectrogram": spec.detach().cpu(),
            "speaker": speaker,
            "phones": tuple(phones),
            "bert": bert.detach().cpu(),
            "text": norm,
        }

    def render_segment(self, request, features, config, control=None, observer=None):
        import torch

        check_cancelled(control, "text.start", observer)
        with runtime_checkpoint(observer, RuntimePhase.RESOURCE, "resources.frontends", "RESOURCE_MISSING", control):
            self._ensure_frontends()
        with runtime_checkpoint(observer, RuntimePhase.TEXT_FRONTEND, "text.g2p", "TEXT_FRONTEND_FAILED", control):
            phones, bert, _ = _clean_text_features(
                request.text, request.language, self.hps.model.version, self.tokenizer,
                self.bert_model, self.device, self.dtype, request.language_resolution,
                g2pw_factory=lambda: self._get_g2pw(control, observer),
            )
        ref_phones = list(features["phones"])
        ref_bert = features["bert"].to(device=self.device, dtype=self.dtype)
        prompt = torch.as_tensor(features["semantic"], dtype=torch.long, device=self.device).view(1, -1)
        text_bert = bert.to(self.device)
        all_phones = torch.tensor([ref_phones + phones], dtype=torch.long, device=self.device)
        check_cancelled(control, "semantic.start", observer)
        with torch.no_grad(), runtime_checkpoint(observer, RuntimePhase.SEMANTIC, "semantic.generate", "SEMANTIC_FAILED", control):
            pred, _ = self.t2s_model.infer_panel(
                all_phones,
                torch.tensor([all_phones.shape[-1]], device=self.device),
                prompt,
                torch.cat([ref_bert, text_bert], dim=1).unsqueeze(0),
                top_k=config.top_k,
                top_p=config.top_p,
                temperature=config.temperature,
                early_stop_num=1500,
            )
            check_cancelled(control, "semantic.complete", observer)
            semantic = pred[:, prompt.shape[1]:].unsqueeze(0)
        with torch.no_grad(), runtime_checkpoint(observer, RuntimePhase.ACOUSTIC, "acoustic.decode", "ACOUSTIC_FAILED", control):
            audio, trace, frames = self.vq_model.decode_with_trace(
                semantic,
                torch.tensor(phones, dtype=torch.long, device=self.device).unsqueeze(0),
                [features["spectrogram"].to(device=self.device, dtype=self.dtype)],
                noise_scale=config.noise_scale,
                speed=config.speed,
                sv_emb=[features["speaker"].to(device=self.device, dtype=self.dtype)],
            )
        check_cancelled(control, "acoustic.complete", observer)
        waveform = audio[0][0] if audio.dim() == 3 else audio.reshape(-1)
        waveform = waveform.detach().cpu().float().numpy()
        peak = float(np.max(np.abs(waveform), initial=0.0))
        if peak > 1:
            waveform = waveform / peak
        split = _split_audio(waveform, frames, config.margin_frame_count, int(self.hps.data.hop_length))
        merged_trace = dict(trace or {})
        merged_trace.update({"left_margin_frames": split["left_margin_frames"], "right_margin_frames": split["right_margin_frames"]})
        return SimpleNamespace(
            core_audio=split["core_audio"], left_margin_audio=split["left_margin_audio"], right_margin_audio=split["right_margin_audio"],
            decoder_frame_count=split["decoder_frame_count"], phone_ids=phones, semantic_tokens=semantic.detach().cpu().reshape(-1).tolist(), trace=merged_trace,
        )

    def render_boundary(self, request, left, right, features, config, control=None, observer=None):
        import torch

        check_cancelled(control, "boundary.start", observer)
        strategy = request.effective_strategy or request.strategy
        if strategy == "crossfade_only":
            left_audio = np.asarray(left.right_margin_audio, dtype=np.float32)
            right_audio = np.asarray(right.left_margin_audio, dtype=np.float32)
            overlap = min(left_audio.size, right_audio.size)
            if overlap == 0:
                audio = np.concatenate([left_audio, right_audio])
            else:
                theta = np.linspace(0, np.pi / 2, overlap, dtype=np.float32)
                audio = np.concatenate([left_audio[:-overlap], np.cos(theta) * left_audio[-overlap:] + np.sin(theta) * right_audio[:overlap], right_audio[overlap:]])
            return SimpleNamespace(boundary_audio=audio.astype(np.float32), boundary_strategy=strategy, trace={"boundary_kind": "crossfade_only"})
        overlap = torch.tensor(left.trace.get("right_margin_frames", []), dtype=torch.float32, device=self.device)
        if overlap.numel() == 0:
            raise ValueError("Left segment is missing boundary margin frames")
        if overlap.ndim == 1:
            overlap = overlap.view(1, 1, -1)
        elif overlap.ndim == 2:
            overlap = overlap.unsqueeze(0)
        with torch.no_grad(), runtime_checkpoint(observer, RuntimePhase.BOUNDARY, "boundary.decode", "BOUNDARY_RENDER_FAILED", control):
            audio, frame_count, trace = self.vq_model.decode_boundary_prefix(
                torch.tensor(right.semantic, dtype=torch.long, device=self.device).view(1, 1, -1),
                torch.tensor(right.phones, dtype=torch.long, device=self.device).unsqueeze(0),
                [features["spectrogram"].to(device=self.device, dtype=self.dtype)],
                left_overlap_frames=overlap,
                boundary_overlap_frame_count=config.boundary_overlap_frame_count,
                boundary_padding_frame_count=config.boundary_padding_frame_count,
                boundary_result_frame_count=config.boundary_result_frame_count,
                noise_scale=config.noise_scale,
                speed=config.speed,
                sv_emb=[features["speaker"].to(device=self.device, dtype=self.dtype)],
            )
        check_cancelled(control, "boundary.complete", observer)
        waveform = (audio[0][0] if audio.dim() == 3 else audio.reshape(-1)).detach().cpu().float().numpy()
        return SimpleNamespace(boundary_audio=waveform, boundary_strategy=strategy, trace={**(trace or {}), "boundary_frame_count": frame_count})

    def synthesize(self, request, control=None, observer=None):
        from .types import SegmentRequest

        features = self.prepare_reference(request.reference, control, observer)
        result = self.render_segment(
            SegmentRequest("synthesis", request.text, request.language, language_resolution=request.language_resolution),
            features, replace(request.config, margin_frame_count=0), control, observer,
        )
        return result.core_audio

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.t2s_model = None
        self.vq_model = None
        self._g2pw = None
        self._frontends_ready = False
        for name in ("ssl_model", "bert_model", "sv_model", "tokenizer"):
            model = getattr(self, name, None)
            if model is not None:
                delattr(self, name)

    def move_to(self, device: str, dtype) -> None:
        import torch

        self.t2s_model.to(device=device, dtype=dtype)
        self.vq_model.to(device=device, dtype=dtype)
        if self._frontends_ready:
            self.ssl_model.to(device=device)
            self.bert_model.to(device=device)
            self.sv_model.embedding_model.to(device=device, dtype=dtype)
            self.sv_model.is_half = dtype == torch.float16
        if device != self.device:
            self._g2pw = None
        self.device = device
        self.dtype = dtype
