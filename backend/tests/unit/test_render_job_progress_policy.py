from pathlib import Path

import pytest


def _load_render_progress_policy() -> dict[str, object]:
    module_path = Path("backend/app/services/render_job_progress_policy.py")
    assert module_path.exists(), "缺少 render job 进度策略模块"

    namespace: dict[str, object] = {}
    exec(module_path.read_text(encoding="utf-8"), namespace)
    return namespace


def test_build_prepare_progress_maps_stages_into_prepare_budget():
    namespace = _load_render_progress_policy()
    build_prepare_progress = namespace["build_prepare_progress"]

    assert build_prepare_progress(completed_stages=0, total_stages=4) == pytest.approx(0.05)
    assert build_prepare_progress(completed_stages=1, total_stages=4) == pytest.approx(0.0875)
    assert build_prepare_progress(completed_stages=2, total_stages=4) == pytest.approx(0.125)
    assert build_prepare_progress(completed_stages=4, total_stages=4) == pytest.approx(0.2)


def test_build_render_segment_progress_supports_custom_progress_window():
    namespace = _load_render_progress_policy()
    build_render_segment_progress = namespace["build_render_segment_progress"]

    assert build_render_segment_progress(
        completed_segments=0,
        total_segments=4,
        start_progress=0.2,
        end_progress=0.6,
    ) == pytest.approx(0.2)
    assert build_render_segment_progress(
        completed_segments=2,
        total_segments=4,
        start_progress=0.2,
        end_progress=0.6,
    ) == pytest.approx(0.4)
    assert build_render_segment_progress(
        completed_segments=4,
        total_segments=4,
        start_progress=0.2,
        end_progress=0.6,
    ) == pytest.approx(0.6)


def test_render_job_service_no_longer_embeds_prepare_or_render_magic_formulas():
    source = Path("backend/app/services/render_job_service.py").read_text(encoding="utf-8")

    assert 'progress=0.05, message="正在准备参考上下文。"' not in source
    assert "0.2 + 0.4 * (index / total_segments)" not in source
    assert "0.2 + 0.25 * (completed_targets / target_total)" not in source
