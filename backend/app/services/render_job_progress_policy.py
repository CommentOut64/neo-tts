from __future__ import annotations

PREPARE_START_PROGRESS = 0.05
PREPARE_END_PROGRESS = 0.2


def _clamp_completed(*, completed: int, total: int) -> float:
    if total <= 0:
        return 1.0
    normalized = min(max(completed, 0), total)
    return normalized / total


def _interpolate_progress(*, ratio: float, start_progress: float, end_progress: float) -> float:
    safe_ratio = max(0.0, min(1.0, float(ratio)))
    return start_progress + (end_progress - start_progress) * safe_ratio


def build_prepare_progress(*, completed_stages: int, total_stages: int) -> float:
    return _interpolate_progress(
        ratio=_clamp_completed(completed=completed_stages, total=total_stages),
        start_progress=PREPARE_START_PROGRESS,
        end_progress=PREPARE_END_PROGRESS,
    )


def build_prepare_progress_from_local(*, local_progress: float) -> float:
    return _interpolate_progress(
        ratio=local_progress,
        start_progress=PREPARE_START_PROGRESS,
        end_progress=PREPARE_END_PROGRESS,
    )


def build_render_segment_progress(
    *,
    completed_segments: int,
    total_segments: int,
    start_progress: float,
    end_progress: float,
) -> float:
    return _interpolate_progress(
        ratio=_clamp_completed(completed=completed_segments, total=total_segments),
        start_progress=start_progress,
        end_progress=end_progress,
    )
