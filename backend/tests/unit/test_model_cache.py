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

    handle = cache.get_model_handle(
        "pretrained_models/gpt.ckpt",
        "pretrained_models/sovits.pth",
        gpt_fingerprint="gpt-fp",
        sovits_fingerprint="sovits-fp",
    )

    assert handle.cache_key.endswith("gpt.ckpt|gpt-fp|%s|sovits-fp" % str((tmp_path / "pretrained_models" / "sovits.pth").resolve()))
    assert handle.gpt_path == str((tmp_path / "pretrained_models" / "gpt.ckpt").resolve())
    assert handle.sovits_path == str((tmp_path / "pretrained_models" / "sovits.pth").resolve())
    assert handle.gpt_fingerprint == "gpt-fp"
    assert handle.sovits_fingerprint == "sovits-fp"


def test_model_cache_creates_new_engine_for_same_paths_when_fingerprint_changes(tmp_path: pathlib.Path):
    created = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        created.append((gpt_path, sovits_path, cnhubert_path, bert_path))
        return {"gpt": gpt_path, "sovits": sovits_path, "index": len(created)}

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
    )

    first = cache.get_engine(
        "pretrained_models/gpt.ckpt",
        "pretrained_models/sovits.pth",
        gpt_fingerprint="gpt-fp-a",
        sovits_fingerprint="sovits-fp-a",
    )
    second = cache.get_engine(
        "pretrained_models/gpt.ckpt",
        "pretrained_models/sovits.pth",
        gpt_fingerprint="gpt-fp-b",
        sovits_fingerprint="sovits-fp-b",
    )

    assert first is not second
    assert len(created) == 2


def test_model_cache_resolves_managed_weight_paths_relative_to_user_data_root(tmp_path: pathlib.Path):
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

    cache.get_engine("managed_voices/demo/weights/demo.ckpt", "managed_voices/demo/weights/demo.pth")

    assert created == [
        (
            str((tmp_path / "storage" / "managed_voices" / "demo" / "weights" / "demo.ckpt").resolve()),
            str((tmp_path / "storage" / "managed_voices" / "demo" / "weights" / "demo.pth").resolve()),
            str((tmp_path / "pretrained_models" / "chinese-hubert-base").resolve()),
            str((tmp_path / "pretrained_models" / "chinese-roberta-wwm-ext-large").resolve()),
        )
    ]


def test_model_cache_default_factory_uses_backend_runtime_module(tmp_path: pathlib.Path, monkeypatch):
    runtime_module = importlib.import_module("backend.app.inference.gsv_runtime_adapter")
    sentinel = object()

    def fake_runtime(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(runtime_module, "GSVRuntimeEngineAdapter", fake_runtime)

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        warmup_hook=lambda engine: None,
    )

    engine = cache.get_engine("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert engine is sentinel


def test_model_cache_build_engine_logs_construction_and_passes_runtime_config(tmp_path, monkeypatch):
    logged = []
    calls = []
    sentinel = object()

    class FakeLogger:
        def info(self, message, *args):
            logged.append(message)

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr("backend.app.inference.model_cache.model_cache_logger", FakeLogger())
    monkeypatch.setattr("backend.app.inference.gsv_runtime_adapter.GSVRuntimeEngineAdapter", factory)
    cache = PyTorchModelCache(
        project_root=tmp_path, cnhubert_base_path="hubert", bert_path="bert",
        inference_device="cpu", inference_dtype="float32", warmup_hook=lambda engine: None,
    )
    engine = cache._build_engine("gpt.ckpt", "sovits.pth", "hubert", "bert")
    assert engine is sentinel
    assert calls == [(("gpt.ckpt", "sovits.pth", str(tmp_path)), {
        "device": "cpu", "dtype": "float32", "cnhubert_path": "hubert", "bert_path": "bert",
        "reference_path_resolver": cache._resolve_path,
    })]
    assert "开始构建 GSV Runtime 实例" in logged
    assert "GSV Runtime 实例构建完成 elapsed_ms={:.2f}" in logged


def test_native_frontend_bootstraps_paths_from_package_location(monkeypatch):
    from runtime.gsv.native import _ensure_gpt_path

    project_root = pathlib.Path(__file__).resolve().parents[3]
    required = {str(project_root), str(project_root / "GPT_SoVITS")}
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry not in required])
    _ensure_gpt_path()
    assert required.issubset(sys.path)


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


class _FakeCacheEngine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.offload_calls = 0
        self.ensure_calls = 0
        self.resident_device = "cuda"

    def offload_from_gpu(self) -> None:
        self.offload_calls += 1
        self.resident_device = "cpu"

    def ensure_on_gpu(self) -> None:
        self.ensure_calls += 1
        self.resident_device = "cuda"


def test_model_cache_acquire_and_release_tracks_usage(tmp_path: pathlib.Path):
    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=lambda *args: _FakeCacheEngine("demo"),
    )

    handle = cache.acquire_model_handle("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert handle.active_count == 1
    assert handle.last_used_at > 0

    cache.release_model_handle(handle.cache_key)

    assert handle.active_count == 0


def test_model_cache_offloads_idle_cuda_handles_before_loading_new_model(tmp_path: pathlib.Path):
    created: list[str] = []

    def fake_factory(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        del sovits_path, cnhubert_path, bert_path
        engine = _FakeCacheEngine(pathlib.Path(gpt_path).name)
        created.append(engine.name)
        return engine

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
        gpu_offload_enabled=True,
        gpu_min_free_mb=2048,
        gpu_reserve_mb_for_load=4096,
        cuda_mem_get_info=lambda: (1024 * 1024 * 1024, 12 * 1024 * 1024 * 1024),
    )

    first = cache.get_model_handle("pretrained_models/a.ckpt", "pretrained_models/a.pth")
    cache.acquire_model_handle("pretrained_models/a.ckpt", "pretrained_models/a.pth")
    cache.release_model_handle(first.cache_key)

    second = cache.acquire_model_handle("pretrained_models/b.ckpt", "pretrained_models/b.pth")

    assert created == ["a.ckpt", "b.ckpt"]
    assert first.engine.offload_calls == 1
    assert first.resident_device == "cpu"
    assert second.active_count == 1


def test_model_cache_acquire_restores_offloaded_engine_to_gpu(tmp_path: pathlib.Path):
    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=lambda *args: _FakeCacheEngine("demo"),
    )

    handle = cache.get_model_handle("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")
    handle.resident_device = "cpu"

    acquired = cache.acquire_model_handle("pretrained_models/gpt.ckpt", "pretrained_models/sovits.pth")

    assert acquired.engine.ensure_calls == 1
    assert acquired.resident_device == "cuda"


def test_model_cache_does_not_offload_pinned_or_active_handles(tmp_path: pathlib.Path):
    created: list[_FakeCacheEngine] = []

    def fake_factory(*args):
        engine = _FakeCacheEngine(f"engine-{len(created)}")
        created.append(engine)
        return engine

    cache = PyTorchModelCache(
        project_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
        engine_factory=fake_factory,
        gpu_offload_enabled=True,
        gpu_min_free_mb=2048,
        gpu_reserve_mb_for_load=4096,
        cuda_mem_get_info=lambda: (1024 * 1024 * 1024, 12 * 1024 * 1024 * 1024),
    )

    pinned = cache.get_model_handle("pretrained_models/pinned.ckpt", "pretrained_models/pinned.pth")
    pinned.pinned = True
    active = cache.acquire_model_handle("pretrained_models/active.ckpt", "pretrained_models/active.pth")

    cache.acquire_model_handle("pretrained_models/new.ckpt", "pretrained_models/new.pth")

    assert pinned.engine.offload_calls == 0
    assert active.engine.offload_calls == 0


def test_model_cache_runtime_flag_uses_application_adapter(tmp_path: pathlib.Path, monkeypatch):
    created = []

    class Adapter:
        resident_device = "cpu"

        def __init__(self, *args, **kwargs):
            created.append(args)
            assert kwargs["device"] == "auto"
            assert kwargs["dtype"] == "float32"

    monkeypatch.setattr(
        "backend.app.inference.gsv_runtime_adapter.GSVRuntimeEngineAdapter",
        Adapter,
    )
    cache = PyTorchModelCache(
        project_root=tmp_path,
        resources_root=tmp_path,
        cnhubert_base_path="pretrained_models/chinese-hubert-base",
        bert_path="pretrained_models/chinese-roberta-wwm-ext-large",
    )
    cache.get_model_handle("model/gpt.ckpt", "model/sovits.pth")
    assert created and created[0][2] == str(tmp_path.resolve())
