from pathlib import Path

import pytest


def _load_render_progress_policy() -> object:
    module_path = Path("backend/app/services/render_job_progress_policy.py")
    assert module_path.exists(), "缺少 render job 进度策略模块"

    namespace: dict[str, object] = {}
    exec(module_path.read_text(encoding="utf-8"), namespace)
    return namespace["build_render_segment_progress"]


def test_build_render_segment_progress_reserves_20_percent_for_preparing():
    build_render_segment_progress = _load_render_progress_policy()

    assert build_render_segment_progress(completed_segments=0, total_segments=4) == pytest.approx(0.2)
    assert build_render_segment_progress(completed_segments=1, total_segments=4) == pytest.approx(0.4)
    assert build_render_segment_progress(completed_segments=2, total_segments=4) == pytest.approx(0.6)
    assert build_render_segment_progress(completed_segments=3, total_segments=4) == pytest.approx(0.8)
    assert build_render_segment_progress(completed_segments=4, total_segments=4) == pytest.approx(1.0)


def test_render_job_service_no_longer_uses_04_segment_budget():
    source = Path("backend/app/services/render_job_service.py").read_text(encoding="utf-8")

    assert "0.2 + 0.4 * (index / total_segments)" not in source
