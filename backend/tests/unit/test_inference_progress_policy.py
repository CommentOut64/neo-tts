from pathlib import Path

import pytest


def _load_progress_policy() -> object:
    module_path = Path("backend/app/inference/progress_policy.py")
    assert module_path.exists(), "缺少独立的推理进度策略模块"

    namespace: dict[str, object] = {}
    exec(module_path.read_text(encoding="utf-8"), namespace)
    return namespace["build_segment_progress"]


def test_build_segment_progress_reserves_preparing_budget_and_evenly_splits_segments():
    build_segment_progress = _load_progress_policy()

    assert build_segment_progress(completed_segments=0, total_segments=4) == pytest.approx(0.2)
    assert build_segment_progress(completed_segments=1, total_segments=4) == pytest.approx(0.4)
    assert build_segment_progress(completed_segments=2, total_segments=4) == pytest.approx(0.6)
    assert build_segment_progress(completed_segments=3, total_segments=4) == pytest.approx(0.8)
    assert build_segment_progress(completed_segments=4, total_segments=4) == pytest.approx(1.0)


def test_build_segment_progress_reaches_completion_exactly_on_last_segment():
    build_segment_progress = _load_progress_policy()

    assert build_segment_progress(completed_segments=0, total_segments=3) == pytest.approx(0.2)
    assert build_segment_progress(completed_segments=1, total_segments=3) == pytest.approx(0.2 + 0.8 / 3)
    assert build_segment_progress(completed_segments=2, total_segments=3) == pytest.approx(0.2 + 0.8 * 2 / 3)
    assert build_segment_progress(completed_segments=3, total_segments=3) == pytest.approx(1.0)


def test_tts_router_does_not_force_progress_back_to_097():
    source = Path("backend/app/api/routers/tts.py").read_text(encoding="utf-8")

    assert "progress=0.97" not in source
