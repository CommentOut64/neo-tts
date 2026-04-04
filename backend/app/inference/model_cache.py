from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from backend.app.inference.types import ModelHandle

if TYPE_CHECKING:
    from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference

EngineFactory = Callable[[str, str, str, str], "GPTSoVITSOptimizedInference"]
WarmupHook = Callable[[Any], None]


class PyTorchModelCache:
    def __init__(
        self,
        project_root: Path,
        cnhubert_base_path: str | Path,
        bert_path: str | Path,
        engine_factory: EngineFactory | None = None,
        warmup_hook: WarmupHook | None = None,
    ) -> None:
        self._project_root = project_root
        self._cnhubert_base_path = self._resolve_path(cnhubert_base_path)
        self._bert_path = self._resolve_path(bert_path)
        self._engine_factory = engine_factory or self._build_engine
        self._warmup_hook = warmup_hook
        self._engines: dict[str, ModelHandle] = {}

    def get_engine(self, gpt_path: str | Path, sovits_path: str | Path) -> Any:
        return self.get_model_handle(gpt_path=gpt_path, sovits_path=sovits_path).engine

    def get_model_handle(self, gpt_path: str | Path, sovits_path: str | Path) -> ModelHandle:
        resolved_gpt_path = self._resolve_path(gpt_path)
        resolved_sovits_path = self._resolve_path(sovits_path)
        cache_key = f"{resolved_gpt_path}|{resolved_sovits_path}"

        if cache_key not in self._engines:
            engine = self._engine_factory(
                resolved_gpt_path,
                resolved_sovits_path,
                self._cnhubert_base_path,
                self._bert_path,
            )
            if self._warmup_hook is not None:
                self._warmup_hook(engine)
            self._engines[cache_key] = ModelHandle(
                cache_key=cache_key,
                gpt_path=resolved_gpt_path,
                sovits_path=resolved_sovits_path,
                engine=engine,
            )
        return self._engines[cache_key]

    def _resolve_path(self, raw_path: str | Path) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._project_root / path
        return str(path.resolve())

    @staticmethod
    def _build_engine(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str) -> Any:
        from backend.app.inference import pytorch_optimized

        return pytorch_optimized.GPTSoVITSOptimizedInference(
            gpt_path,
            sovits_path,
            cnhubert_path,
            bert_path,
        )
