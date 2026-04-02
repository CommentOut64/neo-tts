from pathlib import Path


def test_backend_runtime_lives_in_backend_app():
    runtime_module = Path("backend/app/inference/pytorch_optimized.py")
    assert runtime_module.exists(), "FastAPI 主线推理实现应位于 backend/app/inference 下。"


def test_legacy_root_entrypoints_are_archived():
    archived_root = Path("legacy/root_entrypoints")
    assert (archived_root / "run_optimized_inference.py").exists(), "旧优化版入口应归档到 legacy/root_entrypoints。"
    assert (archived_root / "run_optimized_inference_legacy_streaming.py").exists(), "旧流式核心也应一起归档。"
    assert (archived_root / "api_server.py").exists(), "legacy API 入口应移出根目录。"
