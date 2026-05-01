import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from backend.app.core.lifespan import _preload_configured_voices
from backend.app.core.settings import AppSettings
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store


def test_sv_module_does_not_prepend_developer_ffmpeg_path(monkeypatch):
    module_name = "GPT_SoVITS.sv"
    original_path = r"C:\Windows\System32;C:\Tools\ffmpeg\bin"

    class _FakeTorch(ModuleType):
        pass

    fake_torch = _FakeTorch("torch")
    fake_torch.load = lambda *args, **kwargs: {}

    fake_eres_module = ModuleType("ERes2NetV2")
    fake_eres_module.ERes2NetV2 = object
    fake_kaldi_module = ModuleType("kaldi")

    monkeypatch.setenv("PATH", original_path)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "ERes2NetV2", fake_eres_module)
    monkeypatch.setitem(sys.modules, "kaldi", fake_kaldi_module)
    sys.modules.pop(module_name, None)

    importlib.import_module(module_name)

    assert Path(sys.modules[module_name].sv_path).as_posix() == "pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"
    assert sys.modules[module_name].os.environ["PATH"] == original_path


def test_japanese_module_uses_user_data_runtime_temp_for_openjtalk_fallback(monkeypatch, tmp_path):
    module_name = "GPT_SoVITS.text.japanese"
    user_data_root = tmp_path / "data"
    copied_paths: list[tuple[str, str]] = []

    fake_pyopenjtalk = ModuleType("pyopenjtalk")
    fake_pyopenjtalk.OPEN_JTALK_DICT_DIR = str(tmp_path / "模型资源" / "open_jtalk_dic").encode("utf-8")

    fake_text_package = ModuleType("text")
    fake_symbols_module = ModuleType("text.symbols")
    fake_symbols_module.punctuation = ["!", "?"]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setattr("shutil.copytree", lambda src, dst: copied_paths.append((src, dst)))
    monkeypatch.setattr("shutil.rmtree", lambda path: None)
    monkeypatch.setitem(sys.modules, "pyopenjtalk", fake_pyopenjtalk)
    monkeypatch.setitem(sys.modules, "text", fake_text_package)
    monkeypatch.setitem(sys.modules, "text.symbols", fake_symbols_module)
    sys.modules.pop(module_name, None)

    importlib.import_module(module_name)

    expected_dir = user_data_root / "runtime_temp" / "ja" / "open_jtalk_dic"
    assert fake_pyopenjtalk.OPEN_JTALK_DICT_DIR.decode("utf-8") == str(expected_dir)
    assert copied_paths == [(str(tmp_path / "模型资源" / "open_jtalk_dic"), str(expected_dir))]


def test_korean_module_uses_user_data_runtime_temp_for_mecab_fallback(monkeypatch, tmp_path):
    module_name = "GPT_SoVITS.text.korean"
    user_data_root = tmp_path / "data"
    copied_paths: list[tuple[str, str]] = []

    fake_text_package = ModuleType("text")
    fake_symbols_module = ModuleType("text.symbols2")
    fake_symbols_module.symbols = ["停"]

    fake_jamo = ModuleType("jamo")
    fake_jamo.h2j = lambda text: text
    fake_jamo.j2hcj = lambda text: text

    fake_ko_pron = ModuleType("ko_pron")
    fake_ko_pron.romanise = lambda text, mode: text

    class _FakeBaseG2p:
        def __init__(self):
            self.check_mecab()

        def check_mecab(self):
            return None

        def __call__(self, text):
            return text

    fake_g2pk2 = ModuleType("g2pk2")
    fake_g2pk2.G2p = _FakeBaseG2p

    class _FakeBaseMecab:
        def __init__(self, dicpath=None):
            self.dicpath = dicpath

    fake_eunjeon = ModuleType("eunjeon")
    fake_eunjeon.Mecab = _FakeBaseMecab

    original_find_spec = importlib.util.find_spec

    def _fake_find_spec(name, package=None):
        if name == "eunjeon":
            return SimpleNamespace(submodule_search_locations=[str(tmp_path / "韩文词典")])
        return original_find_spec(name, package)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    monkeypatch.setattr("shutil.copytree", lambda src, dst: copied_paths.append((src, dst)))
    monkeypatch.setattr("shutil.rmtree", lambda path: None)
    monkeypatch.setitem(sys.modules, "text", fake_text_package)
    monkeypatch.setitem(sys.modules, "text.symbols2", fake_symbols_module)
    monkeypatch.setitem(sys.modules, "jamo", fake_jamo)
    monkeypatch.setitem(sys.modules, "ko_pron", fake_ko_pron)
    monkeypatch.setitem(sys.modules, "g2pk2", fake_g2pk2)
    monkeypatch.setitem(sys.modules, "eunjeon", fake_eunjeon)
    sys.modules.pop(module_name, None)

    importlib.import_module(module_name)

    expected_dicpath = user_data_root / "runtime_temp" / "ko" / "ko_dict" / "mecabrc"
    mecab_instance = sys.modules["eunjeon"].Mecab()
    assert mecab_instance.dicpath == str(expected_dicpath)
    assert copied_paths == [
        (str(tmp_path / "韩文词典" / "data"), str(user_data_root / "runtime_temp" / "ko" / "ko_dict"))
    ]


def test_default_adapter_definition_store_skips_gpt_sovits_when_family_is_not_installed():
    store = build_default_adapter_definition_store(enable_gpt_sovits_local=False)

    assert store.get("gpt_sovits_local") is None
    assert store.require("external_http_tts").adapter_id == "external_http_tts"


def test_default_adapter_definition_store_marks_gpt_sovits_local_as_incremental_render_capable():
    store = build_default_adapter_definition_store(enable_gpt_sovits_local=True)

    assert store.require("gpt_sovits_local").capabilities.incremental_render is True


def test_preload_configured_voices_skips_when_gpt_sovits_adapter_is_unavailable(tmp_path):
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "config" / "voices.json",
        preload_on_start=True,
        preload_voice_ids=("demo",),
        gpt_sovits_adapter_installed=False,
    )
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    model_cache = SimpleNamespace(
        get_model_handle=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not preload model handle")),
        get_engine=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not preload engine")),
    )

    _preload_configured_voices(app, model_cache)
