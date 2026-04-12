import pathlib
import importlib
import sys

from backend.app.inference.model_cache import PyTorchModelCache


def test_model_cache_reuses_engine_for_same_resolved_paths(tmp_path: pathlib.Path):
    created = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        created.append((gpt_path, sovits_path, cnhubert_path, bert_path))
        return {"gpt": gpt_path, "sovits": sovits_path}

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
    )

    first = cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")
    second = cache.get_engine(
        str((tmp_path / "pretrained_models" / "gpt.ckpt").resolve()),
        str((tmp_path / "pretrained_models" / "sovits.pth").resolve()),
    )

    assert first is second
    assert len(created) == 1


def test_model_cache_creates_new_engine_for_different_model_paths(tmp_path: pathlib.Path):
    created = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        created.append((gpt_path, sovits_path, cnhubert_path, bert_path))
        return {"gpt": gpt_path, "sovits": sovits_path}

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
    )

    first = cache.get_engine("pretrained_models/gpt_a.ckpt", "pretrained_models/sovits_a.pth")
    second = cache.get_engine("pretrained_models/gpt_b.ckpt", "pretrained_models/sovits_b.pth")

    assert first is not second
    assert len(created) == 2


def test_model_cache_runs_warmup_once_per_new_engine(tmp_path: pathlib.Path):
    created = []
    warmed = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        engine = {"gpt": gpt_path, "sovits": sovits_path}
        created.append(engine)
        return engine

    def fake_warmup(engine):
        warmed.append(engine["gpt"])

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
        warmup_hook=fake_warmup,
    )

    cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")
    cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert len(created) == 1
    assert len(warmed) == 1


def test_model_cache_exposes_model_handle_with_normalized_paths(tmp_path: pathlib.Path):
    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        return {"gpt": gpt_path, "sovits": sovits_path}

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
    )

    handle = cache.get_model_handle("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert handle.cache_key.endswith("gpt.ckpt|%s" % str((tmp_path / "pretrained_models" / "sovits.pth").resolve()))
    assert handle.gpt_path == str((tmp_path / "pretrained_models" / "gpt.ckpt").resolve())
    assert handle.sovits_path == str((tmp_path / "pretrained_models" / "sovits.pth").resolve())


def test_model_cache_default_factory_uses_backend_runtime_module(tmp_path: pathlib.Path, monkeypatch):
    runtime_module = importlib.import_module("backend.app.inference.pytorch_optimized")
    sentinel = object()

    def fake_runtime(*args):
        return sentinel

    monkeypatch.setattr(runtime_module, "GPTSoVITSOptimizedInference", fake_runtime)

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        warmup_hook=lambda engine: None,
    )

    engine = cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert engine is sentinel


def test_pytorch_runtime_bootstraps_gpt_sovits_import_paths():
    runtime_module = importlib.import_module("backend.app.inference.pytorch_optimized")
    project_root = pathlib.Path(__file__).resolve().parents[3]
    gpt_sovits_root = str((project_root / "GPT_SoVITS").resolve())
    repo_root = str(project_root.resolve())

    sys.path[:] = [entry for entry in sys.path if entry not in {repo_root, gpt_sovits_root}]
    importlib.reload(runtime_module)

    assert repo_root in sys.path
    assert gpt_sovits_root in sys.path


def test_model_cache_clear_drops_cached_engines(tmp_path: pathlib.Path):
    created = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        engine = {"gpt": gpt_path, "sovits": sovits_path, "created_index": len(created)}
        created.append((gpt_path, sovits_path, cnhubert_path, bert_path))
        return engine

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
    )

    first = cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")
    cache.clear()
    second = cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert first is not second
    assert len(created) == 2
