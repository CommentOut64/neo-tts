from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from backend.app.core.logging import get_logger
from backend.app.core.path_resolution import resolve_runtime_path
from backend.app.inference.asset_fingerprint import content_sha256
from backend.app.inference.types import ModelCacheIdentity, ModelHandle
from runtime.gsv.frontend_pool import SharedFrontendPool

if TYPE_CHECKING:
    from backend.app.inference.gsv_runtime_adapter import GSVRuntimeEngineAdapter

EngineFactory = Callable[[str, str, str, str], "GSVRuntimeEngineAdapter"]
WarmupHook = Callable[[Any], None]
CudaMemGetInfo = Callable[[], tuple[int, int]]
model_cache_logger = get_logger("model_cache")


def build_model_cache_from_settings(*, settings: Any, model_cache_cls: type["PyTorchModelCache"]) -> "PyTorchModelCache":
    candidate_kwargs = {
        "project_root": settings.project_root,
        "user_data_root": settings.user_data_root,
        "resources_root": settings.resources_root,
        "managed_voices_dir": settings.managed_voices_dir,
        "cnhubert_base_path": settings.cnhubert_base_path,
        "bert_path": settings.bert_path,
        "gpu_offload_enabled": settings.gpu_offload_enabled,
        "gpu_min_free_mb": settings.gpu_min_free_mb,
        "gpu_reserve_mb_for_load": settings.gpu_reserve_mb_for_load,
        "inference_device": getattr(settings, "inference_device", "auto"),
        "inference_dtype": getattr(settings, "inference_dtype", "float32"),
    }
    supported_parameters = inspect.signature(model_cache_cls).parameters
    constructor_kwargs = {
        key: value
        for key, value in candidate_kwargs.items()
        if key in supported_parameters
    }
    return model_cache_cls(**constructor_kwargs)


class PyTorchModelCache:
    def __init__(
        self,
        project_root: Path,
        cnhubert_base_path: str | Path,
        bert_path: str | Path,
        user_data_root: Path | None = None,
        resources_root: Path | None = None,
        managed_voices_dir: Path | None = None,
        engine_factory: EngineFactory | None = None,
        warmup_hook: WarmupHook | None = None,
        gpu_offload_enabled: bool = True,
        gpu_min_free_mb: int = 2048,
        gpu_reserve_mb_for_load: int = 4096,
        inference_device: str = "auto",
        inference_dtype: str = "float32",
        cuda_mem_get_info: CudaMemGetInfo | None = None,
    ) -> None:
        self._project_root = project_root
        self._user_data_root = user_data_root
        self._resources_root = resources_root
        self._managed_voices_dir = managed_voices_dir
        self._cnhubert_base_path = self._resolve_path(cnhubert_base_path)
        self._bert_path = self._resolve_path(bert_path)
        self._inference_device = inference_device
        self._inference_dtype = inference_dtype
        self._engine_factory = engine_factory or self._build_engine
        self._warmup_hook = warmup_hook
        self._gpu_offload_enabled = gpu_offload_enabled
        self._gpu_min_free_bytes = max(gpu_min_free_mb, 0) * 1024 * 1024
        self._gpu_reserve_bytes_for_load = max(gpu_reserve_mb_for_load, 0) * 1024 * 1024
        self._cuda_mem_get_info = cuda_mem_get_info or self._default_cuda_mem_get_info()
        self._engines: dict[str, ModelHandle] = {}
        self._retiring: dict[str, ModelHandle] = {}
        self._inflight: dict[str, threading.Event] = {}
        self._inflight_failures: dict[str, BaseException] = {}
        self._frontend_pool = SharedFrontendPool()
        self._retirement_callbacks: dict[tuple[str, str], list[Callable[[], None]]] = {}
        self._lock = threading.RLock()

    def get_engine(
        self,
        gpt_path: str | Path,
        sovits_path: str | Path,
        *,
        gpt_fingerprint: str | None = None,
        sovits_fingerprint: str | None = None,
    ) -> Any:
        return self.get_model_handle(
            gpt_path=gpt_path,
            sovits_path=sovits_path,
            gpt_fingerprint=gpt_fingerprint,
            sovits_fingerprint=sovits_fingerprint,
        ).engine

    def get_model_handle(
        self,
        gpt_path: str | Path,
        sovits_path: str | Path,
        *,
        gpt_fingerprint: str | None = None,
        sovits_fingerprint: str | None = None,
    ) -> ModelHandle:
        identity = self._build_cache_identity(
            gpt_path=gpt_path,
            sovits_path=sovits_path,
            gpt_fingerprint=gpt_fingerprint,
            sovits_fingerprint=sovits_fingerprint,
        )
        cache_key = identity.cache_key
        with self._lock:
            # Retiring handles are kept solely for existing leases. New callers
            # must construct/acquire a fresh ready handle for the same identity.
            handle = self._engines.get(cache_key)
            if handle is not None:
                model_cache_logger.debug("模型缓存命中 cache_key={}", cache_key)
                return handle
            event = self._inflight.get(cache_key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[cache_key] = event
                self._inflight_failures.pop(cache_key, None)
        if not owner:
            assert event is not None
            event.wait()
            with self._lock:
                handle = self._engines.get(cache_key)
                failure = self._inflight_failures.get(cache_key)
            if failure is not None:
                raise failure
            if handle is None:
                raise RuntimeError("Model construction failed in another request.")
            return handle

        try:
            with self._lock:
                self._offload_idle_handles_before_new_load(cache_key=cache_key)
            init_started = time.perf_counter()
            model_cache_logger.info("模型缓存未命中，开始初始化引擎 cache_key={}", cache_key)
            engine = self._engine_factory(identity.gpt_path, identity.sovits_path, self._cnhubert_base_path, self._bert_path)
            if self._warmup_hook is not None:
                self._warmup_hook(engine)
            handle = ModelHandle(
                cache_key=cache_key, gpt_path=identity.gpt_path, sovits_path=identity.sovits_path,
                engine=engine, gpt_fingerprint=identity.gpt_fingerprint, sovits_fingerprint=identity.sovits_fingerprint,
                last_used_at=time.perf_counter(), resident_device=self._detect_resident_device(engine),
                target_device=identity.target_device, target_dtype=identity.dtype,
            )
            with self._lock:
                self._engines[cache_key] = handle
            model_cache_logger.info("模型引擎初始化完成 cache_key={} elapsed_ms={:.2f}", cache_key, (time.perf_counter() - init_started) * 1000)
            return handle
        except BaseException as exc:
            with self._lock:
                self._inflight_failures[cache_key] = exc
            raise
        finally:
            with self._lock:
                completed = self._inflight.pop(cache_key, None)
                if completed is not None:
                    completed.set()

    def acquire_model_handle(
        self,
        gpt_path: str | Path,
        sovits_path: str | Path,
        *,
        gpt_fingerprint: str | None = None,
        sovits_fingerprint: str | None = None,
    ) -> ModelHandle:
        handle = self.get_model_handle(
            gpt_path=gpt_path,
            sovits_path=sovits_path,
            gpt_fingerprint=gpt_fingerprint,
            sovits_fingerprint=sovits_fingerprint,
        )
        with self._lock:
            if handle.resident_device == "cpu" and handle.target_device == "cuda":
                ensure_on_gpu = getattr(handle.engine, "ensure_on_gpu", None)
                if callable(ensure_on_gpu):
                    ensure_on_gpu()
                    handle.resident_device = self._detect_resident_device(handle.engine)
            handle.active_count += 1
            handle.state = "active"
            handle.last_used_at = time.perf_counter()
            return handle

    def release_model_handle(self, cache_key: str) -> None:
        callbacks: list[Callable[[], None]] = []
        with self._lock:
            handle = self._engines.get(cache_key) or self._retiring.get(cache_key)
            if handle is None:
                model_cache_logger.warning("释放模型句柄时未命中 cache_key={}", cache_key)
                return
            if handle.active_count > 0:
                handle.active_count -= 1
            handle.last_used_at = time.perf_counter()
            if handle.active_count == 0 and handle.state == "active":
                handle.state = "hot"
            if handle.active_count == 0 and handle.state == "retiring":
                self._retiring.pop(cache_key, None)
                close = getattr(handle.engine, "close", None)
                if callable(close):
                    close()
            callbacks = self._completed_retirement_callbacks_locked()
        for callback in callbacks:
            callback()

    def clear(self) -> None:
        with self._lock:
            handles = []
            for key, handle in tuple(self._engines.items()):
                self._engines.pop(key)
                if handle.active_count:
                    handle.state = "retiring"
                    self._retiring[key] = handle
                else:
                    handles.append(handle)
        for handle in handles:
            close = getattr(handle.engine, "close", None)
            if callable(close):
                close()

    def invalidate_revision(self, *, gpt_fingerprint: str, sovits_fingerprint: str) -> None:
        self.retire_revision(
            gpt_fingerprint=gpt_fingerprint,
            sovits_fingerprint=sovits_fingerprint,
        )

    def retire_revision(self, *, gpt_fingerprint: str, sovits_fingerprint: str, on_retired: Callable[[], None] | None = None) -> bool:
        """Retire matching model identities; active leases close after release."""
        callbacks: list[Callable[[], None]] = []
        revision = (gpt_fingerprint, sovits_fingerprint)
        with self._lock:
            if on_retired is not None:
                self._retirement_callbacks.setdefault(revision, []).append(on_retired)
            for key, handle in tuple(self._engines.items()):
                if handle.gpt_fingerprint == gpt_fingerprint and handle.sovits_fingerprint == sovits_fingerprint:
                    self._engines.pop(key)
                    if handle.active_count:
                        handle.state = "retiring"
                        self._retiring[key] = handle
                    else:
                        close = getattr(handle.engine, "close", None)
                        if callable(close):
                            close()
            active = any(
                handle.gpt_fingerprint == gpt_fingerprint
                and handle.sovits_fingerprint == sovits_fingerprint
                for handle in (*self._engines.values(), *self._retiring.values())
            )
            callbacks = self._completed_retirement_callbacks_locked()
        for callback in callbacks:
            callback()
        return active

    def _completed_retirement_callbacks_locked(self) -> list[Callable[[], None]]:
        completed: list[Callable[[], None]] = []
        for revision, callbacks in tuple(self._retirement_callbacks.items()):
            if any(
                handle.gpt_fingerprint == revision[0] and handle.sovits_fingerprint == revision[1]
                for handle in (*self._engines.values(), *self._retiring.values())
            ):
                continue
            self._retirement_callbacks.pop(revision, None)
            completed.extend(callbacks)
        return completed

    def is_revision_active(self, *, gpt_fingerprint: str, sovits_fingerprint: str) -> bool:
        with self._lock:
            return any(
                handle.gpt_fingerprint == gpt_fingerprint
                and handle.sovits_fingerprint == sovits_fingerprint
                and handle.active_count > 0
                for handle in (*self._engines.values(), *self._retiring.values())
            )

    def _resolve_path(self, raw_path: str | Path) -> str:
        return str(
            resolve_runtime_path(
                raw_path,
                project_root=self._project_root,
                user_data_root=self._user_data_root,
                resources_root=self._resources_root,
                managed_voices_dir=self._managed_voices_dir,
            )
        )

    def _build_cache_identity(
        self,
        *,
        gpt_path: str | Path,
        sovits_path: str | Path,
        gpt_fingerprint: str | None,
        sovits_fingerprint: str | None,
    ) -> ModelCacheIdentity:
        resolved_gpt_path = self._resolve_path(gpt_path)
        resolved_sovits_path = self._resolve_path(sovits_path)
        return ModelCacheIdentity(
            gpt_path=resolved_gpt_path,
            sovits_path=resolved_sovits_path,
            gpt_fingerprint=self._resolve_fingerprint(resolved_gpt_path, gpt_fingerprint),
            sovits_fingerprint=self._resolve_fingerprint(resolved_sovits_path, sovits_fingerprint),
            target_device=self._resolved_target_device(),
            dtype=self._inference_dtype,
        )

    @staticmethod
    def _resolve_fingerprint(resolved_path: str, explicit_fingerprint: str | None) -> str:
        # Legacy callers still carry path probes under this argument. Cache
        # identity must always be derived from the checkpoint's actual bytes.
        del explicit_fingerprint
        return content_sha256(resolved_path)

    @staticmethod
    def _default_cuda_mem_get_info() -> CudaMemGetInfo | None:
        try:
            import torch
        except ImportError:
            return None
        if not hasattr(torch, "cuda") or not torch.cuda.is_available() or not hasattr(torch.cuda, "mem_get_info"):
            return None
        return torch.cuda.mem_get_info

    @staticmethod
    def _detect_resident_device(engine: Any) -> str:
        resident_device = getattr(engine, "resident_device", None)
        if isinstance(resident_device, str) and resident_device:
            return resident_device
        device = getattr(engine, "device", None)
        if device is not None:
            return str(device)
        return "cpu"

    def _is_gpu_pressure_high(self) -> bool:
        if not self._gpu_offload_enabled or self._cuda_mem_get_info is None:
            return False
        try:
            free_bytes, _ = self._cuda_mem_get_info()
        except Exception as exc:
            model_cache_logger.warning("读取 GPU 显存信息失败，跳过卸载兜底 reason={}", exc)
            return False
        threshold_bytes = max(self._gpu_min_free_bytes, self._gpu_reserve_bytes_for_load)
        return free_bytes < threshold_bytes

    def _offload_idle_handles_before_new_load(self, *, cache_key: str) -> None:
        if not self._is_gpu_pressure_high():
            return

        candidates = sorted(
            (
                handle
                for existing_key, handle in self._engines.items()
                if existing_key != cache_key
                and handle.resident_device == "cuda"
                and handle.active_count == 0
                and not handle.pinned
                and callable(getattr(handle.engine, "offload_from_gpu", None))
            ),
            key=lambda item: item.last_used_at,
        )
        for handle in candidates:
            if not self._is_gpu_pressure_high():
                break
            handle.engine.offload_from_gpu()
            handle.resident_device = self._detect_resident_device(handle.engine)
            handle.last_used_at = time.perf_counter()
            model_cache_logger.warning(
                "检测到 GPU 显存压力，已卸载空闲模型到 CPU cache_key={}",
                handle.cache_key,
            )

    def _build_engine(self, gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str) -> Any:
        started = time.perf_counter()
        model_cache_logger.info("开始构建 GSV Runtime 实例")
        from backend.app.inference.gsv_runtime_adapter import GSVRuntimeEngineAdapter
        engine = GSVRuntimeEngineAdapter(
            gpt_path, sovits_path, str(self._resources_root or self._project_root),
            device=self._inference_device, dtype=self._inference_dtype,
            cnhubert_path=cnhubert_path, bert_path=bert_path,
            frontend_pool=self._frontend_pool,
            reference_path_resolver=self._resolve_path,
        )
        model_cache_logger.info("GSV Runtime 实例构建完成 elapsed_ms={:.2f}", (time.perf_counter() - started) * 1000)
        return engine

    def _resolved_target_device(self) -> str:
        """Resolve auto once for cache identity; preserve explicit cuda for runtime errors."""
        if self._inference_device != "auto":
            return self._inference_device
        try:
            import torch
            return "cuda" if bool(torch.cuda.is_available()) else "cpu"
        except Exception:
            return "cpu"
