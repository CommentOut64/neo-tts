import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_langsegmenter_uses_pretrained_models_root_env_for_fast_langdetect_cache(monkeypatch):
    module_name = "GPT_SoVITS.text.LangSegmenter.langsegmenter"
    package_name = "GPT_SoVITS.text.LangSegmenter"
    app_core_cwd = Path(r"F:\portable\packages\app-core\v0.1.0")
    pretrained_models_root = Path(r"F:\portable\packages\pretrained-models\support-v1")

    monkeypatch.setenv("NEO_TTS_PRETRAINED_MODELS_ROOT", str(pretrained_models_root))
    monkeypatch.setattr("os.getcwd", lambda: str(app_core_cwd))

    fake_jieba = ModuleType("jieba")
    fake_jieba.setLogLevel = lambda _level: None

    class _FakeLangDetectConfig:
        def __init__(self, cache_dir: str):
            self.cache_dir = cache_dir

    class _FakeLangDetector:
        def __init__(self, config):
            self.config = config

    fake_fast_langdetect = ModuleType("fast_langdetect")
    fake_fast_langdetect.infer = SimpleNamespace(
        LangDetectConfig=_FakeLangDetectConfig,
        LangDetector=_FakeLangDetector,
        _default_detector=None,
    )

    fake_split_lang = ModuleType("split_lang")

    class _FakeLangSplitter:
        def __init__(self, *args, **kwargs):
            del args, kwargs

    fake_split_lang.LangSplitter = _FakeLangSplitter

    monkeypatch.setitem(sys.modules, "jieba", fake_jieba)
    monkeypatch.setitem(sys.modules, "fast_langdetect", fake_fast_langdetect)
    monkeypatch.setitem(sys.modules, "split_lang", fake_split_lang)
    sys.modules.pop(module_name, None)
    sys.modules.pop(package_name, None)

    importlib.import_module(module_name)

    configured_detector = fake_fast_langdetect.infer._default_detector
    assert configured_detector is not None
    assert configured_detector.config.cache_dir == str(
        pretrained_models_root / "pretrained_models" / "fast_langdetect"
    )
