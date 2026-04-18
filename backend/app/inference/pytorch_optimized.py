from __future__ import annotations

import gc
import os
import sys
import threading
import time
from pathlib import Path

import librosa
import numpy as np
import torch
import torchaudio
from transformers import AutoModelForMaskedLM, AutoTokenizer

from backend.app.core.logging import get_logger
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    ResolvedVoiceBinding,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
    build_render_asset_id,
    fingerprint_inference_config,
    split_segment_audio,
)
from backend.app.schemas.edit_session import InitializeEditSessionRequest

def _ensure_gpt_sovits_import_paths() -> None:
    resources_root_env = os.environ.get("NEO_TTS_RESOURCES_ROOT")
    gpt_sovits_root_env = os.environ.get("NEO_TTS_GPT_SOVITS_ROOT")
    project_root = (
        Path(resources_root_env).resolve()
        if resources_root_env
        else Path(__file__).resolve().parents[3]
    )
    gpt_sovits_root = (
        Path(gpt_sovits_root_env).resolve()
        if gpt_sovits_root_env
        else (project_root / "GPT_SoVITS").resolve()
    )
    required_paths = (
        str(project_root),
        str(gpt_sovits_root),
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
from backend.app.inference.progress_policy import (
    PREPARING_BOOTSTRAP_PROGRESS,
    PREPARING_REFERENCE_READY_PROGRESS,
    PREPARING_SEGMENTED_PROGRESS,
    build_segment_progress,
)
from backend.app.inference.text_processing import (
    OFFICIAL_SPLIT_PUNCTUATION,
    build_phones_and_bert_features,
    split_text_segments_official,
)
from backend.app.text.segment_standardizer import build_segment_render_text
from backend.app.inference.types import InferenceCancelledError

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IS_HALF = DEVICE == "cuda"
_WARMUP_HEARTBEAT_INTERVAL_SECONDS = 10.0
inference_logger = get_logger("pytorch_inference")


def _resolve_segment_inference_language(segment) -> str:
    declared_language = (getattr(segment, "text_language", "") or "auto").lower()
    detected_language = (getattr(segment, "detected_language", "unknown") or "unknown").lower()
    if declared_language in {"auto", "unknown", ""} and detected_language in {"zh", "ja", "en"}:
        return detected_language
    return declared_language or "auto"


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
        self.resident_device = DEVICE
        init_started = time.perf_counter()

        inference_logger.info("Loading models on {} (half precision: {})", DEVICE, IS_HALF)

        ssl_started = time.perf_counter()
        cnhubert.cnhubert_base_path = cnhubert_base_path
        self.ssl_model = cnhubert.get_model()
        if self.is_half:
            self.ssl_model = self.ssl_model.half()
        self.ssl_model = self.ssl_model.to(self.device)
        inference_logger.info("CNHubert 加载完成 elapsed_ms={:.2f}", (time.perf_counter() - ssl_started) * 1000)

        bert_started = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(bert_path)
        self.bert_model = AutoModelForMaskedLM.from_pretrained(bert_path)
        if self.is_half:
            self.bert_model = self.bert_model.half()
        self.bert_model = self.bert_model.to(self.device)
        inference_logger.info("BERT 加载完成 elapsed_ms={:.2f}", (time.perf_counter() - bert_started) * 1000)

        gpt_started = time.perf_counter()
        dict_s1 = torch.load(gpt_path, map_location="cpu")
        self.config = dict_s1["config"]
        self.t2s_model = Text2SemanticLightningModule(self.config, "****", is_train=False)
        self.t2s_model.load_state_dict(dict_s1["weight"])
        if self.is_half:
            self.t2s_model = self.t2s_model.half()
        self.t2s_model = self.t2s_model.to(self.device)
        self.t2s_model.eval()
        inference_logger.info("GPT 权重加载完成 elapsed_ms={:.2f}", (time.perf_counter() - gpt_started) * 1000)

        sovits_started = time.perf_counter()
        dict_s2 = load_sovits_new(sovits_path)
        self.hps = DictToAttrRecursive(dict_s2["config"])
        self.hps.model.semantic_frame_rate = "25hz"

        _, model_version, _ = get_sovits_version_from_path_fast(sovits_path)
        if "config" in dict_s2 and "model" in dict_s2["config"] and "version" in dict_s2["config"]["model"]:
            model_version = dict_s2["config"]["model"]["version"]
        elif "sv_emb.weight" in dict_s2["weight"]:
            model_version = "v2Pro"

        self.hps.model.version = model_version
        inference_logger.info("Detected SoVITS model version: {}", model_version)

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
        inference_logger.info("SoVITS 权重加载完成 elapsed_ms={:.2f}", (time.perf_counter() - sovits_started) * 1000)

        sv_started = time.perf_counter()
        self.sv_model = SV(self.device, self.is_half)
        inference_logger.info("声纹模型加载完成 elapsed_ms={:.2f}", (time.perf_counter() - sv_started) * 1000)

        self.warmup()
        inference_logger.info("模型初始化完成 total_ms={:.2f}", (time.perf_counter() - init_started) * 1000)

    def offload_from_gpu(self) -> None:
        if self.resident_device != "cuda":
            return
        self._move_runtime_to_device("cpu")
        self.resident_device = "cpu"

    def ensure_on_gpu(self) -> None:
        if self.resident_device == "cuda":
            return
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available, cannot restore model to GPU.")
        self._move_runtime_to_device("cuda")
        self.resident_device = "cuda"

    def _move_runtime_to_device(self, target_device: str) -> None:
        inference_logger.info("迁移推理模型 device={} -> {}", self.resident_device, target_device)
        self.ssl_model = self.ssl_model.to(target_device)
        self.bert_model = self.bert_model.to(target_device)
        self.t2s_model = self.t2s_model.to(target_device)
        self.vq_model = self.vq_model.to(target_device)
        self.sv_model.embedding_model = self.sv_model.embedding_model.to(target_device)
        if target_device == "cpu":
            gc.collect()
        if hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()
        if self.device != target_device:
            self.device = target_device

    def _describe_cuda_memory(self) -> str:
        if not torch.cuda.is_available() or not hasattr(torch.cuda, "mem_get_info"):
            return "unavailable"
        try:
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            allocated_bytes = torch.cuda.memory_allocated() if hasattr(torch.cuda, "memory_allocated") else 0
            reserved_bytes = torch.cuda.memory_reserved() if hasattr(torch.cuda, "memory_reserved") else 0
        except Exception as exc:
            return f"error:{exc}"
        mib = 1024 * 1024
        return (
            f"free_mb={free_bytes / mib:.0f} "
            f"total_mb={total_bytes / mib:.0f} "
            f"allocated_mb={allocated_bytes / mib:.0f} "
            f"reserved_mb={reserved_bytes / mib:.0f}"
        )

    def _log_warmup_context(self) -> None:
        resident_device = getattr(self, "resident_device", self.device)
        inference_logger.info(
            "Warmup context device={} resident_device={} half={} pid={} thread_id={} cuda_mem={}",
            self.device,
            resident_device,
            self.is_half,
            os.getpid(),
            threading.get_ident(),
            self._describe_cuda_memory(),
        )

    def _log_warmup_stage_begin(
        self,
        stage_state: dict[str, str | float],
        stage: str,
        detail: str,
    ) -> float:
        stage_started = time.perf_counter()
        stage_state["stage"] = stage
        stage_state["detail"] = detail
        stage_state["stage_started"] = stage_started
        inference_logger.info("Warmup stage begin stage={} detail={}", stage, detail)
        return stage_started

    def _log_warmup_stage_end(self, stage: str, stage_started: float, detail: str) -> None:
        inference_logger.info(
            "Warmup stage end stage={} stage_elapsed_ms={:.2f} detail={}",
            stage,
            (time.perf_counter() - stage_started) * 1000,
            detail,
        )

    def _run_warmup_watchdog(
        self,
        stop_event: threading.Event,
        stage_state: dict[str, str | float],
        warmup_started: float,
    ) -> None:
        while not stop_event.wait(_WARMUP_HEARTBEAT_INTERVAL_SECONDS):
            stage_started = float(stage_state.get("stage_started", warmup_started))
            resident_device = getattr(self, "resident_device", self.device)
            inference_logger.warning(
                "Warmup still running stage={} stage_elapsed_ms={:.2f} total_elapsed_ms={:.2f} device={} resident_device={} half={} pid={} thread_id={} cuda_mem={} detail={}",
                str(stage_state.get("stage", "unknown")),
                (time.perf_counter() - stage_started) * 1000,
                (time.perf_counter() - warmup_started) * 1000,
                self.device,
                resident_device,
                self.is_half,
                os.getpid(),
                threading.get_ident(),
                self._describe_cuda_memory(),
                str(stage_state.get("detail", "-")),
            )

    @staticmethod
    def _describe_value_shape(value) -> str:
        shape = getattr(value, "shape", None)
        if shape is None:
            return type(value).__name__
        try:
            return str(tuple(shape))
        except TypeError:
            return str(shape)

    def warmup(self):
        warmup_started = time.perf_counter()
        stage = "bootstrap"
        stage_state: dict[str, str | float] = {
            "stage": stage,
            "detail": "bootstrap",
            "stage_started": warmup_started,
        }
        inference_logger.info("Warming up models (GPT, SoVITS, BERT, etc.)...")
        self._log_warmup_context()
        watchdog_stop_event = threading.Event()
        watchdog_thread = threading.Thread(
            target=self._run_warmup_watchdog,
            args=(watchdog_stop_event, stage_state, warmup_started),
            name="warmup-watchdog",
            daemon=True,
        )
        watchdog_thread.start()
        try:
            stage = "phones_and_bert_en"
            stage_started = self._log_warmup_stage_begin(stage_state, stage, "text='Warmup text.' lang=en")
            phones, _, norm_text_en = self.get_phones_and_bert("Warmup text.", "en", self.hps.model.version)
            self._log_warmup_stage_end(
                stage,
                stage_started,
                f"phones={len(phones)} norm_text_len={len(norm_text_en)}",
            )

            stage = "phones_and_bert_zh"
            stage_started = self._log_warmup_stage_begin(stage_state, stage, "text='你好，预热文本。' lang=zh")
            _, _, norm_text_zh = self.get_phones_and_bert("你好，预热文本。", "zh", self.hps.model.version)
            self._log_warmup_stage_end(stage, stage_started, f"norm_text_len={len(norm_text_zh)}")

            inference_logger.info("Warming up GPU kernels...")
            with torch.no_grad():
                stage = "prepare_dummy_inputs"
                stage_started = self._log_warmup_stage_begin(stage_state, stage, f"phone_count={len(phones)}")
                dummy_prompt = torch.zeros((1, 1), dtype=torch.long, device=self.device)
                dummy_bert = torch.zeros(
                    (1, 1024, len(phones) + 1),
                    dtype=torch.float16 if self.is_half else torch.float32,
                    device=self.device,
                )
                dummy_phones = torch.LongTensor(phones + [0]).unsqueeze(0).to(self.device)
                dummy_phones_len = torch.tensor([dummy_phones.shape[-1]]).to(self.device)
                self._log_warmup_stage_end(
                    stage,
                    stage_started,
                    "dummy_prompt_shape={} dummy_bert_shape={} dummy_phones_shape={} dummy_phones_len_shape={}".format(
                        self._describe_value_shape(dummy_prompt),
                        self._describe_value_shape(dummy_bert),
                        self._describe_value_shape(dummy_phones),
                        self._describe_value_shape(dummy_phones_len),
                    ),
                )

                stage = "t2s_infer_panel"
                stage_started = self._log_warmup_stage_begin(
                    stage_state,
                    stage,
                    "dummy_phones_shape={} dummy_bert_shape={}".format(
                        self._describe_value_shape(dummy_phones),
                        self._describe_value_shape(dummy_bert),
                    ),
                )
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
                if pred_semantic is None:
                    raise RuntimeError("warmup infer_panel returned no semantic tokens")
                self._log_warmup_stage_end(
                    stage,
                    stage_started,
                    "pred_semantic_shape={} dummy_prefix_len={}".format(
                        self._describe_value_shape(pred_semantic),
                        dummy_prompt.shape[1],
                    ),
                )

                stage = "prepare_dummy_semantic"
                stage_started = self._log_warmup_stage_begin(stage_state, stage, "building decode inputs")
                prepare_dummy_semantic_started = stage_started
                dummy_spec = torch.zeros((1, self.hps.data.filter_length // 2 + 1, 10), device=self.device)
                if self.is_half:
                    dummy_spec = dummy_spec.half()
                dummy_prefix_len = dummy_prompt.shape[1]
                dummy_semantic = pred_semantic[:, dummy_prefix_len:].unsqueeze(0)
                dummy_sv_emb = None
                if getattr(self.vq_model, "is_v2pro", False):
                    sv_stage = "build_dummy_sv_embedding"
                    sv_stage_started = self._log_warmup_stage_begin(stage_state, sv_stage, "vq_model.is_v2pro=True")
                    dummy_sv_emb = [self._build_dummy_warmup_speaker_embedding()]
                    self._log_warmup_stage_end(
                        sv_stage,
                        sv_stage_started,
                        f"sv_emb_shape={self._describe_value_shape(dummy_sv_emb[0])}",
                    )
                    stage_state["stage"] = stage
                    stage_state["detail"] = "building decode inputs"
                    stage_state["stage_started"] = prepare_dummy_semantic_started
                self._log_warmup_stage_end(
                    stage,
                    prepare_dummy_semantic_started,
                    "dummy_semantic_shape={} dummy_spec_shape={} has_sv_emb={}".format(
                        self._describe_value_shape(dummy_semantic),
                        self._describe_value_shape(dummy_spec),
                        dummy_sv_emb is not None,
                    ),
                )

                stage = "vq_decode"
                stage_started = self._log_warmup_stage_begin(
                    stage_state,
                    stage,
                    "dummy_semantic_shape={} phone_count={} has_sv_emb={}".format(
                        self._describe_value_shape(dummy_semantic),
                        len(phones),
                        dummy_sv_emb is not None,
                    ),
                )
                _ = self.vq_model.decode(
                    dummy_semantic,
                    torch.LongTensor(phones).unsqueeze(0).to(self.device),
                    [dummy_spec],
                    sv_emb=dummy_sv_emb,
                )
                self._log_warmup_stage_end(stage, stage_started, "decode_call_completed")
            if torch.cuda.is_available():
                stage = "cuda_synchronize"
                stage_started = self._log_warmup_stage_begin(stage_state, stage, "torch.cuda.synchronize")
                torch.cuda.synchronize()
                self._log_warmup_stage_end(stage, stage_started, "cuda_sync_completed")
            inference_logger.info("Warmup completed elapsed_ms={:.2f}", (time.perf_counter() - warmup_started) * 1000)
        except Exception as exc:
            inference_logger.exception("Warmup failed at stage={} reason={}", stage, str(exc))
        finally:
            watchdog_stop_event.set()
            watchdog_thread.join(timeout=1.0)

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

    def _build_dummy_warmup_speaker_embedding(self) -> torch.Tensor:
        dummy_audio_16k = torch.zeros(
            (1, int(16000 * 0.3)),
            dtype=torch.float16 if self.is_half else torch.float32,
            device=self.device,
        )
        return self.sv_model.compute_embedding3(dummy_audio_16k)

    @staticmethod
    def _coerce_resolved_context(
        request_or_context: ResolvedRenderContext | InitializeEditSessionRequest,
    ) -> ResolvedRenderContext:
        if isinstance(request_or_context, ResolvedRenderContext):
            return request_or_context
        return ResolvedRenderContext(
            voice_id=request_or_context.voice_id,
            model_key=request_or_context.model_id,
            reference_audio_path=request_or_context.reference_audio_path or "",
            reference_text=request_or_context.reference_text or "",
            reference_language=request_or_context.reference_language or "",
            speed=request_or_context.speed,
            top_k=request_or_context.top_k,
            top_p=request_or_context.top_p,
            temperature=request_or_context.temperature,
            noise_scale=request_or_context.noise_scale,
            resolved_voice_binding=ResolvedVoiceBinding(
                voice_binding_id="binding-initialize",
                voice_id=request_or_context.voice_id,
                model_key=request_or_context.model_id,
            ),
        )

    def build_reference_context(
        self,
        request_or_context: ResolvedRenderContext | InitializeEditSessionRequest,
    ) -> ReferenceContext:
        context_started = time.perf_counter()
        resolved_context = self._coerce_resolved_context(request_or_context)
        if (
            not resolved_context.reference_audio_path
            or not resolved_context.reference_text
            or not resolved_context.reference_language
        ):
            raise ValueError("Editable inference requires reference_audio_path, reference_text and reference_language.")

        reference_audio_path = self._resolve_reference_audio_path(resolved_context.reference_audio_path)
        reference_text = ensure_sentence_end(resolved_context.reference_text, resolved_context.reference_language)
        inference_config = {
            "speed": resolved_context.speed,
            "top_k": resolved_context.top_k,
            "top_p": resolved_context.top_p,
            "temperature": resolved_context.temperature,
            "noise_scale": resolved_context.noise_scale,
            "margin_frame_count": 6,
            "boundary_overlap_frame_count": 6,
            "boundary_padding_frame_count": 4,
            "boundary_result_frame_count": 6,
        }
        fingerprint = fingerprint_inference_config(inference_config)
        prompt_started = time.perf_counter()
        prompt_semantic = self._extract_prompt_semantic(reference_audio_path)
        prompt_elapsed_ms = (time.perf_counter() - prompt_started) * 1000
        spec_started = time.perf_counter()
        refer_spec, refer_audio = self.get_spepc(reference_audio_path)
        spec_elapsed_ms = (time.perf_counter() - spec_started) * 1000
        speaker_started = time.perf_counter()
        speaker_embedding = self._compute_reference_speaker_embedding(refer_audio)
        speaker_elapsed_ms = (time.perf_counter() - speaker_started) * 1000
        inference_logger.info(
            "Reference context built voice_id={} fingerprint={} prompt_semantic_ms={:.2f} spectrogram_ms={:.2f} speaker_embedding_ms={:.2f} total_ms={:.2f}",
            resolved_context.voice_id,
            fingerprint[:12],
            prompt_elapsed_ms,
            spec_elapsed_ms,
            speaker_elapsed_ms,
            (time.perf_counter() - context_started) * 1000,
        )

        return ReferenceContext(
            reference_context_id=f"{resolved_context.voice_id}:{fingerprint[:12]}",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=reference_audio_path,
            reference_text=reference_text,
            reference_language=resolved_context.reference_language,
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
        *,
        progress_callback=None,
    ) -> SegmentRenderAssetPayload:
        _emit_progress(
            progress_callback,
            status="preparing",
            progress=0.1,
            message="正在准备本次推理",
            current_segment=0,
            total_segments=1,
        )
        prompt_phones, prompt_bert, _ = self.get_phones_and_bert(
            context.reference_text,
            context.reference_language,
            self.hps.model.version,
        )
        segment_inference_language = _resolve_segment_inference_language(segment)
        if segment_inference_language != segment.text_language:
            inference_logger.info(
                "segment inference language resolved segment_id={} declared_language={} detected_language={} resolved_language={}",
                segment.segment_id,
                segment.text_language,
                getattr(segment, "detected_language", "unknown"),
                segment_inference_language,
            )
        segment_text = build_segment_render_text(
            stem=segment.stem,
            text_language=segment_inference_language,
            terminal_raw=getattr(segment, "terminal_raw", ""),
            terminal_closer_suffix=getattr(segment, "terminal_closer_suffix", ""),
            terminal_source=getattr(segment, "terminal_source", "synthetic"),
        )
        segment_phones, segment_bert, _ = self.get_phones_and_bert(
            segment_text,
            segment_inference_language,
            self.hps.model.version,
            default_lang=context.reference_language,
        )
        _emit_progress(
            progress_callback,
            status="inferencing",
            progress=0.35,
            message="正在生成语音内容",
            current_segment=0,
            total_segments=1,
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
            _emit_progress(
                progress_callback,
                status="inferencing",
                progress=0.7,
                message="正在生成语音内容",
                current_segment=0,
                total_segments=1,
            )
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
        _emit_progress(
            progress_callback,
            status="completed",
            progress=1.0,
            message="正在生成语音内容",
            current_segment=1,
            total_segments=1,
        )

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
        effective_boundary_strategy = getattr(edge, "effective_boundary_strategy", None) or edge.boundary_strategy
        if effective_boundary_strategy == "crossfade_only":
            boundary_audio = self._build_crossfade_only_boundary_audio(left_asset, right_asset)
            return BoundaryAssetPayload(
                boundary_asset_id=build_boundary_asset_id(
                    left_segment_id=edge.left_segment_id,
                    left_render_version=left_asset.render_version,
                    right_segment_id=edge.right_segment_id,
                    right_render_version=right_asset.render_version,
                    edge_version=edge.edge_version,
                    boundary_strategy=effective_boundary_strategy,
                ),
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=effective_boundary_strategy,
                boundary_sample_count=int(boundary_audio.shape[-1]),
                boundary_audio=boundary_audio,
                trace={"boundary_kind": "crossfade_only"},
            )
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
                boundary_strategy=effective_boundary_strategy,
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=effective_boundary_strategy,
            boundary_sample_count=int(boundary_np.shape[-1]),
            boundary_audio=boundary_np,
            trace=merged_trace,
        )

    @staticmethod
    def _build_crossfade_only_boundary_audio(
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
    ) -> np.ndarray:
        left_margin = left_asset.right_margin_audio.astype(np.float32, copy=False)
        right_margin = right_asset.left_margin_audio.astype(np.float32, copy=False)
        if left_margin.size == 0:
            return right_margin.copy()
        if right_margin.size == 0:
            return left_margin.copy()

        overlap = min(int(left_margin.size), int(right_margin.size))
        prefix = left_margin[:-overlap]
        suffix = right_margin[overlap:]
        theta = np.linspace(0.0, np.pi / 2.0, overlap, endpoint=True, dtype=np.float32)
        crossfaded = (np.cos(theta) * left_margin[-overlap:] + np.sin(theta) * right_margin[:overlap]).astype(
            np.float32,
            copy=False,
        )
        return np.concatenate([prefix, crossfaded, suffix]).astype(np.float32, copy=False)

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
        inference_logger.info("Inferencing text_lang={} text={}", text_lang, text)
        _emit_progress(
            progress_callback,
            status="preparing",
            progress=PREPARING_BOOTSTRAP_PROGRESS,
            message="推理已启动，正在准备输入。",
        )
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
            progress=PREPARING_SEGMENTED_PROGRESS,
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
        _emit_progress(
            progress_callback,
            status="preparing",
            progress=PREPARING_REFERENCE_READY_PROGRESS,
            message="参考音频特征已准备。",
            current_segment=0,
            total_segments=len(segments),
        )
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
            inference_logger.debug("Processing segment {}/{}: {}", index + 1, len(segments), seg)
            _emit_progress(
                progress_callback,
                status="inferencing",
                progress=build_segment_progress(completed_segments=index, total_segments=len(segments)),
                message=f"正在处理第 {index + 1}/{len(segments)} 段。",
                current_segment=index,
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
            if index < len(segments) - 1:
                _emit_progress(
                    progress_callback,
                    status="inferencing",
                    progress=build_segment_progress(completed_segments=index + 1, total_segments=len(segments)),
                    message=f"第 {index + 1}/{len(segments)} 段处理完成。",
                    current_segment=index + 1,
                    total_segments=len(segments),
                )

        t_all_end = time.perf_counter()

        _raise_if_cancelled(should_cancel)
        audio_final = np.concatenate(final_audios) if final_audios else np.zeros(0, dtype=np.float32)

        total_audio_duration = len(audio_final) / sr
        total_inference_time = t_all_end - t_all_start
        rtf = total_inference_time / total_audio_duration if total_audio_duration > 0 else 0
        gpt_tps = total_gpt_tokens / total_gpt_time if total_gpt_time > 0 else 0

        inference_logger.info(
            "Inference summary ref_proc_s={:.3f} text_clean_s={:.3f} gpt_s={:.3f} gpt_tps={:.2f} sovits_s={:.3f} first_segment_s={:.3f} audio_s={:.3f} total_s={:.3f} rtf={:.4f}",
            t_ref_end - t_ref_start,
            total_text_time,
            total_gpt_time,
            gpt_tps,
            total_sovits_time,
            t_first_segment,
            total_audio_duration,
            total_inference_time,
            rtf,
        )
        _emit_progress(
            progress_callback,
            status="completed",
            progress=1.0,
            message="推理完成。",
            current_segment=len(segments),
            total_segments=len(segments),
        )

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
