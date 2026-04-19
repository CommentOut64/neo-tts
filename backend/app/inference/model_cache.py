from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from backend.app.core.logging import get_logger
from backend.app.inference.types import ModelHandle

if TYPE_CHECKING:
    from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference

EngineFactory = Callable[[str, str, str, str], "GPTSoVITSOptimizedInference"]
WarmupHook = Callable[[Any], None]
CudaMemGetInfo = Callable[[], tuple[int, int]]
model_cache_logger = get_logger("model_cache")


def build_model_cache_from_settings(*, settings: Any, model_cache_cls: type["PyTorchModelCache"]) -> "PyTorchModelCache":
    candidate_kwargs = {
        "project_root": settings.project_root,
        "cnhubert_base_path": settings.cnhubert_base_path,
        "bert_path": settings.bert_path,
        "gpu_offload_enabled": settings.gpu_offload_enabled,
        "gpu_min_free_mb": settings.gpu_min_free_mb,
        "gpu_reserve_mb_for_load": settings.gpu_reserve_mb_for_load,
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
        engine_factory: EngineFactory | None = None,
        warmup_hook: WarmupHook | None = None,
        gpu_offload_enabled: bool = True,
        gpu_min_free_mb: int = 2048,
        gpu_reserve_mb_for_load: int = 4096,
        cuda_mem_get_info: CudaMemGetInfo | None = None,
    ) -> None:
        self._project_root = project_root
        self._cnhubert_base_path = self._resolve_path(cnhubert_base_path)
        self._bert_path = self._resolve_path(bert_path)
        self._engine_factory = engine_factory or self._build_engine
        self._warmup_hook = warmup_hook
        self._gpu_offload_enabled = gpu_offload_enabled
        self._gpu_min_free_bytes = max(gpu_min_free_mb, 0) * 1024 * 1024
        self._gpu_reserve_bytes_for_load = max(gpu_reserve_mb_for_load, 0) * 1024 * 1024
        self._cuda_mem_get_info = cuda_mem_get_info or self._default_cuda_mem_get_info()
        self._engines: dict[str, ModelHandle] = {}
        self._lock = threading.RLock()

    def get_engine(self, gpt_path: str | Path, sovits_path: str | Path) -> Any:
        return self.get_model_handle(gpt_path=gpt_path, sovits_path=sovits_path).engine

    def get_model_handle(self, gpt_path: str | Path, sovits_path: str | Path) -> ModelHandle:
        resolved_gpt_path = self._resolve_path(gpt_path)
        resolved_sovits_path = self._resolve_path(sovits_path)
        cache_key = f"{resolved_gpt_path}|{resolved_sovits_path}"
        with self._lock:
            handle = self._engines.get(cache_key)
            if handle is not None:
                model_cache_logger.debug("模型缓存命中 cache_key={}", cache_key)
                return handle

            self._offload_idle_handles_before_new_load(cache_key=cache_key)

            init_started = time.perf_counter()
            model_cache_logger.info(
                "模型缓存未命中，开始初始化引擎 cache_key={}",
                cache_key,
            )
            engine = self._engine_factory(
                resolved_gpt_path,
                resolved_sovits_path,
                self._cnhubert_base_path,
                self._bert_path,
            )
            if self._warmup_hook is not None:
                self._warmup_hook(engine)
            handle = ModelHandle(
                cache_key=cache_key,
                gpt_path=resolved_gpt_path,
                sovits_path=resolved_sovits_path,
                engine=engine,
                last_used_at=time.perf_counter(),
                resident_device=self._detect_resident_device(engine),
            )
            self._engines[cache_key] = handle
            model_cache_logger.info(
                "模型引擎初始化完成 cache_key={} elapsed_ms={:.2f}",
                cache_key,
                (time.perf_counter() - init_started) * 1000,
            )
            return handle

    def acquire_model_handle(self, gpt_path: str | Path, sovits_path: str | Path) -> ModelHandle:
        with self._lock:
            handle = self.get_model_handle(gpt_path=gpt_path, sovits_path=sovits_path)
            if handle.resident_device == "cpu":
                ensure_on_gpu = getattr(handle.engine, "ensure_on_gpu", None)
                if callable(ensure_on_gpu):
                    ensure_on_gpu()
                    handle.resident_device = "cuda"
            handle.active_count += 1
            handle.last_used_at = time.perf_counter()
            return handle

    def release_model_handle(self, cache_key: str) -> None:
        with self._lock:
            handle = self._engines.get(cache_key)
            if handle is None:
                model_cache_logger.warning("释放模型句柄时未命中 cache_key={}", cache_key)
                return
            if handle.active_count > 0:
                handle.active_count -= 1
            handle.last_used_at = time.perf_counter()

    def clear(self) -> None:
        with self._lock:
            self._engines.clear()

    def _resolve_path(self, raw_path: str | Path) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._project_root / path
        return str(path.resolve())

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
        if callable(getattr(engine, "offload_from_gpu", None)) or callable(getattr(engine, "ensure_on_gpu", None)):
            return "cuda"
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
            handle.resident_device = "cpu"
            handle.last_used_at = time.perf_counter()
            model_cache_logger.warning(
                "检测到 GPU 显存压力，已卸载空闲模型到 CPU cache_key={}",
                handle.cache_key,
            )

    @staticmethod
    def _build_engine(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str) -> Any:
        import_started = time.perf_counter()
        model_cache_logger.info("开始导入 PyTorch 推理模块")
        from backend.app.inference import pytorch_optimized
        model_cache_logger.info(
            "PyTorch 推理模块导入完成 elapsed_ms={:.2f}",
            (time.perf_counter() - import_started) * 1000,
        )

        construct_started = time.perf_counter()
        model_cache_logger.info(
            "开始构建 PyTorch 推理实例 gpt_path={} sovits_path={}",
            gpt_path,
            sovits_path,
        )
        engine = pytorch_optimized.GPTSoVITSOptimizedInference(
            gpt_path,
            sovits_path,
            cnhubert_path,
            bert_path,
        )
        model_cache_logger.info(
            "PyTorch 推理实例构建完成 elapsed_ms={:.2f}",
            (time.perf_counter() - construct_started) * 1000,
        )
        return engine
