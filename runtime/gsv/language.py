from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import RuntimeDiagnostic, RuntimeFailure, RuntimePhase, emit, error_info
from .diagnostics import runtime_entrypoint


@dataclass(frozen=True, slots=True)
class LanguageSpan:
    text: str
    language: str


@dataclass(frozen=True, slots=True)
class LanguageResolution:
    mode: str
    spans: tuple[LanguageSpan, ...]
    fallback: str | None = None
    source_text: str | None = field(default=None, repr=False, compare=False)
    declared_language: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "spans", tuple(self.spans))

    @property
    def mixed(self) -> bool:
        return len({span.language for span in self.spans}) > 1

    @property
    def inference_language(self) -> str:
        if self.fallback == "auto" or self.mode in {"mixed", "unknown"}:
            return "auto"
        return self.mode

    def matches(self, declared_language: str, text: str) -> bool:
        content = " ".join(text.split())
        return (
            self.source_text == content
            and self.declared_language == (declared_language or "auto").lower()
            and re.sub(r"\s", "", "".join(span.text for span in self.spans)) == re.sub(r"\s", "", content)
        )


_HAN = re.compile(r"[\u3400-\u9fff]")
_KANA = re.compile(r"[\u3040-\u30ff]")
_LATIN = re.compile(r"[A-Za-z]")
_SEGMENTER_LOCK = threading.RLock()


class LanguageResolutionService:
    def __init__(self, resources_root: str | None = None) -> None:
        self._resources_root = Path(resources_root) if resources_root else Path(__file__).resolve().parents[2]
        self._detector = None

    def close(self) -> None:
        with _SEGMENTER_LOCK:
            self._detector = None

    def resolve_or_reuse(self, declared_language: str, text: str, resolution=None, *, observer=None) -> LanguageResolution:
        if resolution is None or not resolution.matches(declared_language, text):
            return self.resolve(declared_language, text, observer=observer)
        if resolution.fallback == "auto":
            emit(observer, RuntimeDiagnostic("language_fallback", RuntimePhase.TEXT_FRONTEND, "language.resolve", {"language_fallback": "auto"}))
        return resolution

    @runtime_entrypoint(RuntimePhase.TEXT_FRONTEND, "language.resolve", "TEXT_FRONTEND_FAILED")
    def resolve(self, declared_language: str, text: str, *, strict: bool = False, observer=None) -> LanguageResolution:
        content = " ".join(text.split())
        if not content:
            raise RuntimeFailure(error_info("TEXT_EMPTY", checkpoint="language.resolve", message="Text is empty."))
        declared = (declared_language or "auto").lower()
        if declared == "en" and (_HAN.search(content) or _KANA.search(content)):
            if strict:
                raise RuntimeFailure(error_info("MIXED_LANGUAGE_REQUIRES_AUTO", checkpoint="language.resolve", message="English mode cannot process mixed-language text."))
            resolution = replace(self.resolve("auto", content, strict=False, observer=observer), fallback="auto", declared_language=declared)
            emit(observer, RuntimeDiagnostic("language_fallback", RuntimePhase.TEXT_FRONTEND, "language.resolve", {"language_fallback": "auto"}))
            return resolution
        if declared in {"zh", "ja", "ko", "en"} and not (
            _LATIN.search(content) and (_HAN.search(content) or _KANA.search(content))
        ):
            return LanguageResolution(declared, (LanguageSpan(content, declared),), source_text=content, declared_language=declared)
        spans = self._official_spans(content, declared if declared in {"zh", "ja", "ko"} else "")
        if not spans:
            spans = (LanguageSpan(content, "unknown"),)
        if re.sub(r"\s", "", "".join(span.text for span in spans)) != re.sub(r"\s", "", content):
            raise RuntimeFailure(error_info("TEXT_FRONTEND_FAILED", checkpoint="language.resolve", message="Language segmentation did not preserve the input text."))
        return LanguageResolution("mixed" if len({item.language for item in spans}) > 1 else spans[0].language, tuple(spans), source_text=content, declared_language=declared)

    @staticmethod
    def _get_segmenter():
        from GPT_SoVITS.text.LangSegmenter import LangSegmenter

        return LangSegmenter

    def _official_spans(self, text: str, default_language: str = "") -> tuple[LanguageSpan, ...]:
        cache_dir = self._resources_root / "pretrained_models" / "fast_langdetect"
        if not (cache_dir / "lid.176.bin").is_file():
            raise RuntimeFailure(error_info("LANGUAGE_RESOURCE_MISSING", checkpoint="language.resources", message="The language detection model is missing."))
        try:
            segmenter = self._get_segmenter()
            from fast_langdetect import infer

            # The official splitter uses fast_langdetect's singleton. Keep its
            # resource selection scoped to this call, including concurrent runtimes.
            with _SEGMENTER_LOCK:
                if self._detector is None:
                    self._detector = infer.LangDetector(infer.LangDetectConfig(cache_dir=str(cache_dir)))
                previous = infer._default_detector
                try:
                    infer._default_detector = self._detector
                    items = segmenter.getTexts(text, default_lang=default_language)
                finally:
                    infer._default_detector = previous
            return tuple(
                LanguageSpan(str(item["text"]), str(item.get("lang", "unknown")))
                for item in items if item.get("text")
            )
        except (ImportError, FileNotFoundError) as exc:
            raise RuntimeFailure(error_info("LANGUAGE_RESOURCE_MISSING", checkpoint="language.resources", message="A language frontend resource is missing."), exc) from exc
        except RuntimeFailure:
            raise
        except Exception as exc:
            raise RuntimeFailure(error_info("TEXT_FRONTEND_FAILED", checkpoint="language.resolve", message="Language detection failed."), exc) from exc
