from __future__ import annotations

import sys
import time
from pathlib import Path

import librosa
import numpy as np
import torch
import torchaudio
from transformers import AutoModelForMaskedLM, AutoTokenizer

from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
    build_render_asset_id,
    fingerprint_inference_config,
    split_segment_audio,
)

def _ensure_gpt_sovits_import_paths() -> None:
    project_root = Path(__file__).resolve().parents[3]
    required_paths = (
        str(project_root),
        str((project_root / "GPT_SoVITS").resolve()),
    )
    for path in required_paths:
        if path not in sys.path:
            sys.path.append(path)


_ensure_gpt_sovits_import_paths()

from GPT_SoVITS.AR.models.t2s_lightning_module import Text2SemanticLightningModule
from GPT_SoVITS.feature_extractor import cnhubert
from GPT_SoVITS.module.models import SynthesizerTrn
from GPT_SoVITS.process_ckpt import get_sovits_version_from_path_fast, load_sovits_new
from GPT_SoVITS.sv import SV
from backend.app.inference.audio_processing import load_reference_spectrogram
from backend.app.inference.text_processing import (
    OFFICIAL_SPLIT_PUNCTUATION,
    build_phones_and_bert_features,
    split_text_segments_official,
)
from backend.app.inference.types import InferenceCancelledError

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IS_HALF = DEVICE == "cuda"


class DictToAttrRecursive(dict):
    def __init__(self, input_dict):
        super().__init__(input_dict)
        for key, value in input_dict.items():
            if isinstance(value, dict):
                value = DictToAttrRecursive(value)
            self[key] = value
            setattr(self, key, value)

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(f"Attribute {item} not found") from exc

    def __setattr__(self, key, value):
        if isinstance(value, dict):
            value = DictToAttrRecursive(value)
        super().__setitem__(key, value)
        super().__setattr__(key, value)

    def __delattr__(self, item):
        try:
            del self[item]
        except KeyError as exc:
            raise AttributeError(f"Attribute {item} not found") from exc


def split_text(text, text_split_method="cut5"):
    return split_text_segments_official(text, text_split_method=text_split_method)


def ensure_sentence_end(text: str, language: str) -> str:
    content = text.strip()
    if not content:
        return content
    if content[-1] not in OFFICIAL_SPLIT_PUNCTUATION:
        content += "." if language == "en" else "。"
    return content


def _raise_if_cancelled(should_cancel) -> None:
    if callable(should_cancel) and should_cancel():
        raise InferenceCancelledError("Inference cancelled by force pause request.")


def _emit_progress(
    progress_callback,
    *,
    status: str,
    progress: float,
    message: str,
    current_segment: int | None = None,
    total_segments: int | None = None,
) -> None:
    if not callable(progress_callback):
        return
    payload = {
        "status": status,
        "progress": max(0.0, min(1.0, float(progress))),
        "message": message,
    }
    if current_segment is not None:
        payload["current_segment"] = current_segment
    if total_segments is not None:
        payload["total_segments"] = total_segments
    progress_callback(payload)


class GPTSoVITSOptimizedInference:
    def __init__(self, gpt_path, sovits_path, cnhubert_base_path, bert_path):
        self.device = DEVICE
        self.is_half = IS_HALF

        print(f"Loading models on {DEVICE} (half precision: {IS_HALF})...")

        cnhubert.cnhubert_base_path = cnhubert_base_path
        self.ssl_model = cnhubert.get_model()
        if self.is_half:
            self.ssl_model = self.ssl_model.half()
        self.ssl_model = self.ssl_model.to(self.device)

        self.tokenizer = AutoTokenizer.from_pretrained(bert_path)
        self.bert_model = AutoModelForMaskedLM.from_pretrained(bert_path)
        if self.is_half:
            self.bert_model = self.bert_model.half()
        self.bert_model = self.bert_model.to(self.device)

        dict_s1 = torch.load(gpt_path, map_location="cpu")
        self.config = dict_s1["config"]
        self.t2s_model = Text2SemanticLightningModule(self.config, "****", is_train=False)
        self.t2s_model.load_state_dict(dict_s1["weight"])
        if self.is_half:
            self.t2s_model = self.t2s_model.half()
        self.t2s_model = self.t2s_model.to(self.device)
        self.t2s_model.eval()

        dict_s2 = load_sovits_new(sovits_path)
        self.hps = DictToAttrRecursive(dict_s2["config"])
        self.hps.model.semantic_frame_rate = "25hz"

        _, model_version, _ = get_sovits_version_from_path_fast(sovits_path)
        if "config" in dict_s2 and "model" in dict_s2["config"] and "version" in dict_s2["config"]["model"]:
            model_version = dict_s2["config"]["model"]["version"]
        elif "sv_emb.weight" in dict_s2["weight"]:
            model_version = "v2Pro"

        self.hps.model.version = model_version
        print(f"Detected SoVITS model version: {model_version}")

        self.vq_model = SynthesizerTrn(
            self.hps.data.filter_length // 2 + 1,
            self.hps.train.segment_size // self.hps.data.hop_length,
            n_speakers=self.hps.data.n_speakers,
            **self.hps.model,
        )

        if self.is_half:
            self.vq_model = self.vq_model.half()
        self.vq_model = self.vq_model.to(self.device)
        self.vq_model.eval()
        self.vq_model.load_state_dict(dict_s2["weight"], strict=False)

        self.sv_model = SV(self.device, self.is_half)

        self.warmup()

    def warmup(self):
        print("Warming up models (GPT, SoVITS, BERT, etc.)...")
        try:
            phones, _, _ = self.get_phones_and_bert("Warmup text.", "en", self.hps.model.version)
            _ = self.get_phones_and_bert("你好，预热文本。", "zh", self.hps.model.version)

            print("Warming up GPU kernels...")
            with torch.no_grad():
                dummy_prompt = torch.zeros((1, 1), dtype=torch.long, device=self.device)
                dummy_bert = torch.zeros(
                    (1, 1024, len(phones) + 1),
                    dtype=torch.float16 if self.is_half else torch.float32,
                    device=self.device,
                )
                dummy_phones = torch.LongTensor(phones + [0]).unsqueeze(0).to(self.device)
                dummy_phones_len = torch.tensor([dummy_phones.shape[-1]]).to(self.device)

                pred_semantic, _ = self.t2s_model.model.infer_panel(
                    dummy_phones,
                    dummy_phones_len,
                    dummy_prompt,
                    dummy_bert,
                    top_k=5,
                    top_p=1,
                    temperature=1,
                    early_stop_num=50,
                )

                dummy_spec = torch.zeros((1, self.hps.data.filter_length // 2 + 1, 10), device=self.device)
                if self.is_half:
                    dummy_spec = dummy_spec.half()
                dummy_prefix_len = dummy_prompt.shape[1]
                dummy_semantic = pred_semantic[:, dummy_prefix_len:].unsqueeze(0)

                _ = self.vq_model.decode(
                    dummy_semantic,
                    torch.LongTensor(phones).unsqueeze(0).to(self.device),
                    [dummy_spec],
                )
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            print("Warmup completed.")
        except Exception as exc:
            print(f"Warmup failed (non-critical): {exc}")

    def get_bert_feature(self, text, word2ph):
        with torch.no_grad():
            inputs = self.tokenizer(text, return_tensors="pt")
            for key in inputs:
                inputs[key] = inputs[key].to(self.device)
            res = self.bert_model(**inputs, output_hidden_states=True)
            res = torch.cat(res["hidden_states"][-3:-2], -1)[0].cpu()[1:-1]

        assert len(word2ph) == len(text)
        phone_level_feature = []
        for index in range(len(word2ph)):
            repeat_feature = res[index].repeat(word2ph[index], 1)
            phone_level_feature.append(repeat_feature)
        phone_level_feature = torch.cat(phone_level_feature, dim=0)
        return phone_level_feature.T

    def get_bert_inf(self, phones, word2ph, norm_text, language):
        language = language.replace("all_", "")
        if language == "zh":
            bert = self.get_bert_feature(norm_text, word2ph).to(self.device)
        else:
            bert = torch.zeros(
                (1024, len(phones)),
                dtype=torch.float16 if self.is_half else torch.float32,
            ).to(self.device)

        return bert

    def get_phones_and_bert(self, text, language, version, default_lang=None):
        phones, bert, norm_text = build_phones_and_bert_features(
            text=text,
            language=language,
            version=version,
            tokenizer=self.tokenizer,
            bert_model=self.bert_model,
            device=self.device,
            is_half=self.is_half,
            default_lang=default_lang,
            return_norm_text=True,
        )
        return phones, bert, norm_text

    def get_spepc(self, filename):
        return load_reference_spectrogram(
            filename=filename,
            device=self.device,
            sampling_rate=self.hps.data.sampling_rate,
            filter_length=self.hps.data.filter_length,
            hop_length=self.hps.data.hop_length,
            win_length=self.hps.data.win_length,
            is_half=self.is_half,
        )

    def _resolve_reference_audio_path(self, value: str) -> str:
        return str(Path(value).expanduser().resolve())

    def _extract_prompt_semantic(self, reference_audio_path: str) -> torch.Tensor:
        zero_wav_16k = torch.zeros(
            int(16000 * 0.3),
            dtype=torch.float16 if self.is_half else torch.float32,
            device=self.device,
        )
        with torch.no_grad():
            wav16k, _ = librosa.load(reference_audio_path, sr=16000)
            wav16k = torch.from_numpy(wav16k).to(self.device)
            if self.is_half:
                wav16k = wav16k.half()
            wav16k = torch.cat([wav16k, zero_wav_16k])
            ssl_content = self.ssl_model.model(wav16k.unsqueeze(0))["last_hidden_state"].transpose(1, 2)
            codes = self.vq_model.extract_latent(ssl_content)
        return codes[0, 0]

    def _compute_reference_speaker_embedding(self, refer_audio: torch.Tensor) -> torch.Tensor:
        if refer_audio.shape[0] > 1:
            refer_audio = refer_audio[0].unsqueeze(0)
        if self.hps.data.sampling_rate != 16000:
            audio_16k = torchaudio.transforms.Resample(self.hps.data.sampling_rate, 16000).to(self.device)(refer_audio)
        else:
            audio_16k = refer_audio
        return self.sv_model.compute_embedding3(audio_16k)

    def build_reference_context(self, request) -> ReferenceContext:
        if not request.reference_audio_path or not request.reference_text or not request.reference_language:
            raise ValueError("Editable inference requires reference_audio_path, reference_text and reference_language.")

        reference_audio_path = self._resolve_reference_audio_path(request.reference_audio_path)
        reference_text = ensure_sentence_end(request.reference_text, request.reference_language)
        inference_config = {
            "speed": request.speed,
            "top_k": request.top_k,
            "top_p": request.top_p,
            "temperature": request.temperature,
            "noise_scale": request.noise_scale,
            "margin_frame_count": 6,
            "boundary_overlap_frame_count": 6,
            "boundary_padding_frame_count": 4,
            "boundary_result_frame_count": 6,
        }
        fingerprint = fingerprint_inference_config(inference_config)
        prompt_semantic = self._extract_prompt_semantic(reference_audio_path)
        refer_spec, refer_audio = self.get_spepc(reference_audio_path)
        speaker_embedding = self._compute_reference_speaker_embedding(refer_audio)

        return ReferenceContext(
            reference_context_id=f"{request.voice_id}:{fingerprint[:12]}",
            voice_id=request.voice_id,
            model_id=request.model_id,
            reference_audio_path=reference_audio_path,
            reference_text=reference_text,
            reference_language=request.reference_language,
            reference_semantic_tokens=prompt_semantic.detach().cpu().numpy(),
            reference_spectrogram=refer_spec,
            reference_speaker_embedding=speaker_embedding,
            inference_config_fingerprint=fingerprint,
            inference_config=inference_config,
        )

    def render_segment_base(
        self,
        segment,
        context: ReferenceContext,
    ) -> SegmentRenderAssetPayload:
        prompt_phones, prompt_bert, _ = self.get_phones_and_bert(
            context.reference_text,
            context.reference_language,
            self.hps.model.version,
        )
        segment_text = ensure_sentence_end(segment.normalized_text or segment.raw_text, segment.text_language)
        segment_phones, segment_bert, _ = self.get_phones_and_bert(
            segment_text,
            segment.text_language,
            self.hps.model.version,
            default_lang=context.reference_language,
        )

        prompt = torch.from_numpy(context.reference_semantic_tokens).long().unsqueeze(0).to(self.device)
        bert = torch.cat([prompt_bert, segment_bert], 1).unsqueeze(0).to(self.device)
        all_phoneme_ids = torch.LongTensor(prompt_phones + segment_phones).to(self.device).unsqueeze(0)
        all_phoneme_len = torch.tensor([all_phoneme_ids.shape[-1]], device=self.device)

        with torch.no_grad():
            pred_semantic, _ = self.t2s_model.model.infer_panel(
                all_phoneme_ids,
                all_phoneme_len,
                prompt,
                bert,
                top_k=context.inference_config["top_k"],
                top_p=context.inference_config["top_p"],
                temperature=context.inference_config["temperature"],
                early_stop_num=50 * 30,
            )
            prefix_len = prompt.shape[1]
            pred_semantic = pred_semantic[:, prefix_len:].unsqueeze(0)
            audio, trace, encoder_frames = self.vq_model.decode_with_trace(
                pred_semantic,
                torch.LongTensor(segment_phones).to(self.device).unsqueeze(0),
                [context.reference_spectrogram],
                noise_scale=context.inference_config["noise_scale"],
                speed=context.inference_config["speed"],
                sv_emb=[context.reference_speaker_embedding],
            )

        audio_tensor = audio[0][0] if audio.dim() == 3 else audio.reshape(-1)
        max_audio = torch.abs(audio_tensor).max()
        if max_audio > 1:
            audio_tensor = audio_tensor / max_audio
        audio_np = audio_tensor.detach().cpu().float().numpy()
        split_result = split_segment_audio(
            audio=audio_np,
            encoder_frames=encoder_frames,
            requested_margin_frame_count=context.inference_config["margin_frame_count"],
            generator_stride_samples=self.hps.data.hop_length,
        )
        merged_trace = dict(trace or {})
        merged_trace["left_margin_frames"] = split_result["left_margin_frames"]
        merged_trace["right_margin_frames"] = split_result["right_margin_frames"]

        semantic_tokens = pred_semantic.detach().cpu().reshape(-1).tolist()
        return SegmentRenderAssetPayload(
            render_asset_id=build_render_asset_id(
                segment_id=segment.segment_id,
                render_version=segment.render_version,
                semantic_tokens=semantic_tokens,
                fingerprint=context.inference_config_fingerprint,
            ),
            segment_id=segment.segment_id,
            render_version=segment.render_version,
            semantic_tokens=semantic_tokens,
            phone_ids=segment_phones,
            decoder_frame_count=split_result["decoder_frame_count"],
            audio_sample_count=int(audio_np.shape[-1]),
            left_margin_sample_count=split_result["left_margin_sample_count"],
            core_sample_count=split_result["core_sample_count"],
            right_margin_sample_count=split_result["right_margin_sample_count"],
            left_margin_audio=split_result["left_margin_audio"],
            core_audio=split_result["core_audio"],
            right_margin_audio=split_result["right_margin_audio"],
            trace=merged_trace,
        )

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        if left_asset.trace is None or "right_margin_frames" not in left_asset.trace:
            raise ValueError("Left segment asset does not contain right_margin_frames for boundary rendering.")

        overlap_frames = torch.tensor(left_asset.trace["right_margin_frames"], dtype=torch.float32, device=self.device)
        if overlap_frames.dim() == 1:
            overlap_frames = overlap_frames.view(1, 1, -1)
        elif overlap_frames.dim() == 2:
            overlap_frames = overlap_frames.unsqueeze(0)

        with torch.no_grad():
            boundary_audio, boundary_frame_count, trace = self.vq_model.decode_boundary_prefix(
                torch.tensor(right_asset.semantic_tokens, dtype=torch.long, device=self.device).view(1, 1, -1),
                torch.tensor(right_asset.phone_ids, dtype=torch.long, device=self.device).unsqueeze(0),
                [context.reference_spectrogram],
                left_overlap_frames=overlap_frames,
                boundary_overlap_frame_count=context.inference_config["boundary_overlap_frame_count"],
                boundary_padding_frame_count=context.inference_config["boundary_padding_frame_count"],
                boundary_result_frame_count=context.inference_config["boundary_result_frame_count"],
                noise_scale=context.inference_config["noise_scale"],
                speed=context.inference_config["speed"],
                sv_emb=[context.reference_speaker_embedding],
            )

        boundary_tensor = boundary_audio[0][0] if boundary_audio.dim() == 3 else boundary_audio.reshape(-1)
        boundary_np = boundary_tensor.detach().cpu().float().numpy()
        merged_trace = dict(trace or {})
        merged_trace["boundary_frame_count"] = boundary_frame_count
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=edge.boundary_strategy,
            boundary_sample_count=int(boundary_np.shape[-1]),
            boundary_audio=boundary_np,
            trace=merged_trace,
        )

    def infer(
        self,
        ref_wav_path,
        prompt_text,
        prompt_lang,
        text,
        text_lang,
        text_split_method="cut5",
        top_k=5,
        top_p=1,
        temperature=1,
        speed=1,
        pause_length=0.3,
        progress_callback=None,
        should_cancel=None,
    ):
        print(f"Inferencing: {text} ({text_lang})")
        _emit_progress(progress_callback, status="preparing", progress=0.02, message="推理已启动，正在准备输入。")
        _raise_if_cancelled(should_cancel)

        if self.device == "cuda":
            torch.cuda.synchronize()
        t_all_start = time.perf_counter()
        prompt_text = ensure_sentence_end(prompt_text, prompt_lang)
        text = text.strip("\n")
        segments = split_text(text, text_split_method=text_split_method)
        if not segments:
            _emit_progress(progress_callback, status="completed", progress=1.0, message="输入为空，返回静音输出。")
            return np.zeros(0), self.hps.data.sampling_rate

        final_audios = []
        sr = self.hps.data.sampling_rate
        pause_audio = np.zeros(
            int(sr * pause_length),
            dtype=np.float16 if self.is_half else np.float32,
        )
        _emit_progress(
            progress_callback,
            status="preparing",
            progress=0.08,
            message=f"文本已切分，共 {len(segments)} 段。",
            current_segment=0,
            total_segments=len(segments),
        )
        _raise_if_cancelled(should_cancel)

        t_ref_start = time.perf_counter()
        zero_wav_16k = torch.zeros(
            int(16000 * 0.3),
            dtype=torch.float16 if self.is_half else torch.float32,
        ).to(self.device)

        with torch.no_grad():
            wav16k, _ = librosa.load(ref_wav_path, sr=16000)
            wav16k = torch.from_numpy(wav16k).to(self.device)
            if self.is_half:
                wav16k = wav16k.half()

            wav16k = torch.cat([wav16k, zero_wav_16k])
            ssl_content = self.ssl_model.model(wav16k.unsqueeze(0))["last_hidden_state"].transpose(1, 2)
            codes = self.vq_model.extract_latent(ssl_content)
            prompt_semantic = codes[0, 0]
            prompt = prompt_semantic.unsqueeze(0).to(self.device)

            refer_spec, refer_audio = self.get_spepc(ref_wav_path)
            if refer_audio.shape[0] > 1:
                refer_audio = refer_audio[0].unsqueeze(0)
            if self.hps.data.sampling_rate != 16000:
                audio_16k = torchaudio.transforms.Resample(self.hps.data.sampling_rate, 16000).to(self.device)(
                    refer_audio
                )
            else:
                audio_16k = refer_audio
            sv_emb = self.sv_model.compute_embedding3(audio_16k)
        _emit_progress(progress_callback, status="preparing", progress=0.15, message="参考音频特征已准备。")
        _raise_if_cancelled(should_cancel)

        phones1, bert1, _ = self.get_phones_and_bert(prompt_text, prompt_lang, self.hps.model.version)
        if self.device == "cuda":
            torch.cuda.synchronize()
        t_ref_end = time.perf_counter()

        total_text_time = 0.0
        total_gpt_time = 0.0
        total_sovits_time = 0.0
        t_first_segment = 0.0
        total_gpt_tokens = 0

        for index, seg in enumerate(segments):
            _raise_if_cancelled(should_cancel)
            seg = ensure_sentence_end(seg, text_lang)
            print(f"Processing segment {index + 1}/{len(segments)}: {seg}")
            _emit_progress(
                progress_callback,
                status="inferencing",
                progress=0.15 + 0.7 * (index / len(segments)),
                message=f"正在处理第 {index + 1}/{len(segments)} 段。",
                current_segment=index + 1,
                total_segments=len(segments),
            )

            t_seg_text_start = time.perf_counter()
            phones2, bert2, _ = self.get_phones_and_bert(
                seg,
                text_lang,
                self.hps.model.version,
                default_lang=prompt_lang,
            )
            if self.device == "cuda":
                torch.cuda.synchronize()
            t_seg_text_end = time.perf_counter()
            total_text_time += t_seg_text_end - t_seg_text_start

            bert = torch.cat([bert1, bert2], 1).unsqueeze(0).to(self.device)
            all_phoneme_ids = torch.LongTensor(phones1 + phones2).to(self.device).unsqueeze(0)
            all_phoneme_len = torch.tensor([all_phoneme_ids.shape[-1]]).to(self.device)
            _raise_if_cancelled(should_cancel)

            t_gpt_start = time.perf_counter()
            with torch.no_grad():
                pred_semantic, idx = self.t2s_model.model.infer_panel(
                    all_phoneme_ids,
                    all_phoneme_len,
                    prompt,
                    bert,
                    top_k=top_k,
                    top_p=top_p,
                    temperature=temperature,
                    early_stop_num=50 * 30,
                )
                prefix_len = prompt.shape[1]
                pred_semantic = pred_semantic[:, prefix_len:].unsqueeze(0)
            if self.device == "cuda":
                torch.cuda.synchronize()
            t_gpt_end = time.perf_counter()
            total_gpt_time += t_gpt_end - t_gpt_start
            total_gpt_tokens += idx
            _raise_if_cancelled(should_cancel)

            t_sovits_start = time.perf_counter()
            with torch.no_grad():
                audio = self.vq_model.decode(
                    pred_semantic,
                    torch.LongTensor(phones2).to(self.device).unsqueeze(0),
                    [refer_spec],
                    speed=speed,
                    sv_emb=[sv_emb],
                )[0][0]
            if self.device == "cuda":
                torch.cuda.synchronize()
            t_sovits_end = time.perf_counter()
            total_sovits_time += t_sovits_end - t_sovits_start

            max_audio = torch.abs(audio).max()
            if max_audio > 1:
                audio = audio / max_audio
            audio_np = audio.cpu().float().numpy()
            final_audios.append(audio_np)
            if pause_length > 0:
                final_audios.append(pause_audio.copy())

            if index == 0:
                t_first_segment = time.perf_counter() - t_all_start
            _emit_progress(
                progress_callback,
                status="inferencing",
                progress=0.15 + 0.7 * ((index + 1) / len(segments)),
                message=f"第 {index + 1}/{len(segments)} 段处理完成。",
                current_segment=index + 1,
                total_segments=len(segments),
            )

        t_all_end = time.perf_counter()

        _emit_progress(progress_callback, status="inferencing", progress=0.92, message="正在拼接最终音频。")
        _raise_if_cancelled(should_cancel)
        audio_final = np.concatenate(final_audios) if final_audios else np.zeros(0, dtype=np.float32)

        total_audio_duration = len(audio_final) / sr
        total_inference_time = t_all_end - t_all_start
        rtf = total_inference_time / total_audio_duration if total_audio_duration > 0 else 0
        gpt_tps = total_gpt_tokens / total_gpt_time if total_gpt_time > 0 else 0

        print("\n--- Inference Performance Summary ---")
        print(f"Reference Processing:  {t_ref_end - t_ref_start:.3f}s")
        print(f"Target Text Cleaning:  {total_text_time:.3f}s")
        print(f"GPT Semantic Gen:      {total_gpt_time:.3f}s ({gpt_tps:.2f} tokens/s)")
        print(f"SoVITS Audio Decode:   {total_sovits_time:.3f}s")
        print(f"First Segment Latency: {t_first_segment:.3f}s")
        print(f"Total Audio Duration:  {total_audio_duration:.3f}s")
        print(f"Total Inference Time:  {total_inference_time:.3f}s")
        print(f"Real Time Factor (RTF): {rtf:.4f}")
        print("-------------------------------------\n")
        _emit_progress(progress_callback, status="completed", progress=1.0, message="推理完成。")

        return audio_final, sr

    def infer_optimized(
        self,
        ref_wav_path,
        prompt_text,
        prompt_lang,
        text,
        text_lang,
        text_split_method="cut5",
        top_k=15,
        top_p=1,
        temperature=1,
        speed=1,
        chunk_length=24,
        noise_scale=0.35,
        history_window=4,
        pause_length=0.3,
        progress_callback=None,
        should_cancel=None,
    ):
        _ = chunk_length, noise_scale, history_window
        audio, _ = self.infer(
            ref_wav_path=ref_wav_path,
            prompt_text=prompt_text,
            prompt_lang=prompt_lang,
            text=text,
            text_lang=text_lang,
            text_split_method=text_split_method,
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
            speed=speed,
            pause_length=pause_length,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        if audio is None or len(audio) == 0:
            return
        yield np.asarray(audio, dtype=np.float32)
