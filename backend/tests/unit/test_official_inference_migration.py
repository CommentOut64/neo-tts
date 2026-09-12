from pathlib import Path
import subprocess
import sys


def test_runtime_import_closure_is_independent_in_fresh_process(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = (
        f"import sys; sys.path.insert(0, {str(root)!r}); import runtime.gsv; "
        "blocked = ('backend', 'fastapi', 'pytorch_lightning', 'torchmetrics', 'GPT_SoVITS.f5_tts'); "
        "assert not [name for name in sys.modules if any(name == item or name.startswith(item + '.') for item in blocked)]"
    )
    result = subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_production_code_cannot_select_retired_application_core():
    root = Path(__file__).resolve().parents[3]
    retired = root / "backend/app/inference/pytorch_optimized.py"
    assert not retired.exists()
    assert (root / "legacy/gsv_application_core/pytorch_optimized.py.txt").is_file()
    for directory in (root / "runtime/gsv", root / "backend/app"):
        for path in directory.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "pytorch_optimized" not in source, path
            assert "LegacyBackend" not in source, path
            assert "NEO_TTS_USE_GSV_RUNTIME" not in source, path


def test_legacy_root_entrypoints_are_archived():
    archived_root = Path("legacy/root_entrypoints")
    assert (archived_root / "run_optimized_inference.py").exists(), "旧优化版入口应归档到 legacy/root_entrypoints。"
    assert (archived_root / "run_optimized_inference_legacy_streaming.py").exists(), "旧流式核心也应一起归档。"
    assert (archived_root / "api_server.py").exists(), "legacy API 入口应移出根目录。"
