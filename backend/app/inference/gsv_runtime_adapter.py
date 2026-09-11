from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.app.core.logging import get_logger
from backend.app.core.path_resolution import resolve_runtime_path
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
    build_render_asset_id,
    fingerprint_inference_config,
)
from backend.app.inference.progress_policy import build_segment_progress
from backend.app.inference.text_processing import (
    ensure_sentence_end,
    split_text_segments_official,
)
from backend.app.inference.types import InferenceCancelledError
from backend.app.text.segment_standardizer import build_segment_render_text
from runtime.gsv import (
    BoundaryRequest,
    Control,
    GSVRuntime,
    ModelSpec,
    ReferenceRequest,
    RenderConfig,
    RuntimeConfig,
    SegmentRequest,
)
from runtime.gsv.errors import RuntimeFailure, check_cancelled

runtime_logger = get_logger("gsv_runtime")


class _RuntimeObserver:
    def __init__(self, callback=None, *, status="inferencing", reference_progress=False):
        self.callback = callback
        self.status = status
        self.reference_progress = reference_progress

    def on_diagnostic(self, event):
        runtime_logger.info(f"Runtime phase={event.phase.value} checkpoint={event.checkpoint} event={event.event} details={dict(event.details)}")
        if callable(self.callback) and event.phase.value != "lifecycle":
            messages = {
                "resource": "正在准备推理资源。", "reference": "正在处理参考音频。",
                "text_frontend": "正在处理文本。", "semantic": "正在生成语音。",
                "acoustic": "正在生成音频。", "boundary": "正在拼接音频。",
            }
            update = {"status": self.status, "message": messages.get(event.phase.value, "正在准备推理。")}
            if self.reference_progress and event.checkpoint == "reference.prepare" and event.event == "success":
                update["progress"] = 1.0
            self.callback(update)

    def on_error(self, info):
        runtime_logger.log(info.severity.upper(), f"Runtime failed code={info.error_code} phase={info.phase.value} checkpoint={info.checkpoint} request_id={info.request_id} job_id={info.job_id} segment_id={info.segment_id} edge_id={info.edge_id}")


class GSVRuntimeEngineAdapter:
    """Application DTO adapter; computation and ownership stay in ``runtime.gsv``."""

    def __init__(self, gpt_path: str, sovits_path: str, resources_root: str, *, device="auto", dtype="float32", cnhubert_path=None, bert_path=None, reference_path_resolver=None) -> None:
        self._reference_path_resolver = reference_path_resolver or (
            lambda path: str(resolve_runtime_path(path, project_root=Path(resources_root)))
        )
        self._spec = ModelSpec(gpt_path, sovits_path)
        self._runtime = GSVRuntime(RuntimeConfig(resources_root, device=device, dtype=dtype, cnhubert_path=cnhubert_path, bert_path=bert_path))
        self._lease = self._runtime.load_model(self._spec, observer=_RuntimeObserver())
        self.hps = SimpleNamespace(data=SimpleNamespace(sampling_rate=self._lease.identity.sample_rate))
        self._target_device = self._lease.identity.device
        self._target_dtype = self._lease.identity.dtype

    @property
    def resident_device(self):
        return self._lease.backend.device

    def build_reference_context(self, resolved_context, *, progress_callback=None, should_cancel=None) -> ReferenceContext:
        features = self._runtime_call(
            self._runtime.prepare_reference,
            self._lease,
            ReferenceRequest(
                self._reference_path_resolver(resolved_context.reference_audio_path),
                ensure_sentence_end(resolved_context.reference_text, resolved_context.reference_language),
                resolved_context.reference_language,
                identity=resolved_context.reference_identity,
                content_revision=resolved_context.reference_audio_fingerprint,
            ),
            Control(should_cancel=should_cancel),
            observer=_RuntimeObserver(progress_callback, status="preparing", reference_progress=True),
        )
        payload = features.payload
        config = {
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
        return ReferenceContext(
            reference_context_id=f"{resolved_context.reference_identity}:{features.content_revision}",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=resolved_context.reference_audio_path,
            reference_text=str(payload.get("text", resolved_context.reference_text)),
            reference_language=resolved_context.reference_language,
            reference_semantic_tokens=np.asarray(payload.get("semantic", ()), dtype=np.int64),
            reference_spectrogram=payload["spectrogram"],
            reference_speaker_embedding=payload["speaker"],
            inference_config_fingerprint=fingerprint_inference_config(config),
            inference_config=config,
            prompt_phones=list(payload.get("phones", ())),
            prompt_bert=payload.get("bert"),
            prompt_norm_text=str(payload.get("text", resolved_context.reference_text)),
            reference_scope=resolved_context.reference_scope,
            reference_identity=resolved_context.reference_identity,
            reference_audio_fingerprint=resolved_context.reference_audio_fingerprint,
            reference_text_fingerprint=resolved_context.reference_text_fingerprint,
            runtime_model_revision=features.model_revision,
            runtime_sovits_revision=features.sovits_revision,
            runtime_processing_revision=features.processing_revision,
        )

    def render_segment_base(self, segment, context: ReferenceContext, *, progress_callback=None, should_cancel=None) -> SegmentRenderAssetPayload:
        text_language = segment.text_language
        detected_language = getattr(segment, "detected_language", "unknown")
        if text_language in {"auto", "unknown", ""} and detected_language != "unknown":
            text_language = detected_language
        request = SegmentRequest(
            segment_id=segment.segment_id,
            text=build_segment_render_text(
                stem=segment.stem,
                text_language=text_language,
                terminal_raw=segment.terminal_raw,
                terminal_closer_suffix=segment.terminal_closer_suffix,
                terminal_source=segment.terminal_source,
            ),
            language=text_language,
            render_version=segment.render_version,
            terminal_raw=segment.terminal_raw,
            terminal_closer_suffix=segment.terminal_closer_suffix,
            terminal_source=segment.terminal_source,
        )
        result = self._runtime_call(
            self._runtime.render_segment,
            self._lease,
            request,
            self._features(context),
            self._config(context),
            Control(segment_id=segment.segment_id, should_cancel=should_cancel),
            observer=_RuntimeObserver(progress_callback),
        )
        trace = dict(result.trace)
        return SegmentRenderAssetPayload(
            render_asset_id=build_render_asset_id(
                segment_id=result.segment_id,
                render_version=result.render_version,
                semantic_tokens=list(result.semantic),
                fingerprint=context.inference_config_fingerprint,
            ),
            segment_id=result.segment_id,
            render_version=result.render_version,
            semantic_tokens=list(result.semantic),
            phone_ids=list(result.phones),
            decoder_frame_count=result.frame_count,
            audio_sample_count=int(result.audio.size),
            left_margin_sample_count=int(np.asarray(result.left_margin_audio).size),
            core_sample_count=int(result.audio.size),
            right_margin_sample_count=int(np.asarray(result.right_margin_audio).size),
            left_margin_audio=np.asarray(result.left_margin_audio, dtype=np.float32).copy(),
            core_audio=np.asarray(result.audio, dtype=np.float32).copy(),
            right_margin_audio=np.asarray(result.right_margin_audio, dtype=np.float32).copy(),
            trace=trace,
        )

    def render_boundary_asset(self, left_asset, right_asset, edge, context, *, should_cancel=None):
        left = self._segment_result(left_asset)
        right = self._segment_result(right_asset)
        result = self._runtime_call(
            self._runtime.render_boundary,
            self._lease,
            BoundaryRequest(
                edge.edge_id,
                edge.left_segment_id,
                edge.right_segment_id,
                edge.edge_version,
                edge.boundary_strategy,
                edge.effective_boundary_strategy,
            ),
            left,
            right,
            self._features(context),
            self._config(context),
            Control(edge_id=edge.edge_id, should_cancel=should_cancel),
            observer=_RuntimeObserver(),
        )
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=result.strategy,
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=result.strategy,
            boundary_sample_count=int(result.audio.size),
            boundary_audio=np.asarray(result.audio, dtype=np.float32).copy(),
            trace=dict(result.trace),
        )

    def infer_optimized(self, *, ref_wav_path, prompt_text, prompt_lang, text, text_lang, top_k=15, top_p=1.0, temperature=1.0, speed=1.0, noise_scale=0.35, should_cancel=None, text_split_method="cut5", pause_length=0.3, progress_callback=None, **kwargs):
        control = Control(should_cancel=should_cancel)
        observer = _RuntimeObserver()
        try:
            check_cancelled(control, "synthesis.start")
            segments = split_text_segments_official(text, text_split_method=text_split_method)
            if not segments:
                return
            config = RenderConfig(top_k=top_k, top_p=top_p, temperature=temperature, speed=speed, noise_scale=noise_scale, margin_frame_count=0)
            reference = self._runtime.prepare_reference(self._lease, ReferenceRequest(self._reference_path_resolver(ref_wav_path), ensure_sentence_end(prompt_text, prompt_lang), prompt_lang), control, observer)
            chunks = []
            for index, segment in enumerate(segments):
                check_cancelled(control, "semantic.start")
                if callable(progress_callback):
                    progress_callback({"status": "inferencing", "progress": build_segment_progress(completed_segments=index, total_segments=len(segments)), "current_segment": index, "total_segments": len(segments), "message": f"Processing segment {index + 1}/{len(segments)}."})
                result = self._runtime.render_segment(self._lease, SegmentRequest(f"synthesis-{index}", ensure_sentence_end(segment, text_lang), text_lang), reference, config, control, observer)
                chunks.append(np.asarray(result.audio, dtype=np.float32))
                if pause_length > 0:
                    chunks.append(np.zeros(int(result.sample_rate * pause_length), dtype=np.float32))
            check_cancelled(control, "output.synthesis")
            if callable(progress_callback):
                progress_callback({"status": "completed", "progress": 1.0, "current_segment": len(segments), "total_segments": len(segments), "message": "Inference completed."})
            check_cancelled(control, "output.publish")
            yield np.concatenate(chunks)
        except RuntimeFailure as exc:
            if exc.info.error_code == "CANCELLED":
                raise InferenceCancelledError(str(exc)) from exc
            raise

    def offload_from_gpu(self) -> None:
        if self.resident_device != "cpu":
            self._lease = self._runtime.move_model(self._lease, "cpu", "float32")

    def ensure_on_gpu(self) -> None:
        if self._target_device == "cuda" and self.resident_device != "cuda":
            self._lease = self._runtime.move_model(self._lease, self._target_device, self._target_dtype)

    def close(self) -> None:
        self._runtime.release(self._lease)
        self._runtime.close()

    @staticmethod
    def _runtime_call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except RuntimeFailure as exc:
            if exc.info.error_code == "CANCELLED":
                raise InferenceCancelledError(str(exc)) from exc
            raise

    def _features(self, context: ReferenceContext):
        from runtime.gsv import ReferenceFeatures

        return ReferenceFeatures(
            reference_id=context.reference_context_id,
            content_revision=context.reference_audio_fingerprint,
            model_revision=context.runtime_model_revision,
            sovits_revision=context.runtime_sovits_revision,
            processing_revision=context.runtime_processing_revision,
            sample_rate=self._lease.identity.sample_rate,
            semantic_tokens=tuple(np.asarray(context.reference_semantic_tokens).reshape(-1).tolist()),
            phones=tuple(context.prompt_phones),
            payload={
                "semantic": np.asarray(context.reference_semantic_tokens),
                "spectrogram": context.reference_spectrogram,
                "speaker": context.reference_speaker_embedding,
                "phones": tuple(context.prompt_phones),
                "bert": context.prompt_bert,
                "text": context.prompt_norm_text,
            },
        )

    @staticmethod
    def _config(context: ReferenceContext) -> RenderConfig:
        values = context.inference_config
        return RenderConfig(
            top_k=int(values.get("top_k", 15)),
            top_p=float(values.get("top_p", 1.0)),
            temperature=float(values.get("temperature", 1.0)),
            speed=float(values.get("speed", 1.0)),
            noise_scale=float(values.get("noise_scale", 0.35)),
            margin_frame_count=int(values.get("margin_frame_count", 6)),
            boundary_overlap_frame_count=int(values.get("boundary_overlap_frame_count", 6)),
            boundary_padding_frame_count=int(values.get("boundary_padding_frame_count", 4)),
            boundary_result_frame_count=int(values.get("boundary_result_frame_count", 6)),
        )

    def _segment_result(self, asset):
        from runtime.gsv import SegmentResult

        return SegmentResult(
            segment_id=asset.segment_id,
            render_version=asset.render_version,
            sample_rate=self._lease.identity.sample_rate,
            audio=np.asarray(asset.core_audio, dtype=np.float32).copy(),
            frame_count=asset.decoder_frame_count,
            phones=tuple(asset.phone_ids),
            semantic=tuple(asset.semantic_tokens),
            left_margin_audio=np.asarray(asset.left_margin_audio, dtype=np.float32).copy(),
            right_margin_audio=np.asarray(asset.right_margin_audio, dtype=np.float32).copy(),
            trace=dict(asset.trace or {}),
        )
