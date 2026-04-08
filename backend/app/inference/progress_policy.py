from __future__ import annotations

PREPARING_PROGRESS_SHARE = 0.2
SEGMENT_PROGRESS_SHARE = 0.8

PREPARING_BOOTSTRAP_PROGRESS = 0.05
PREPARING_SEGMENTED_PROGRESS = 0.1
PREPARING_REFERENCE_READY_PROGRESS = PREPARING_PROGRESS_SHARE


def build_segment_progress(*, completed_segments: int, total_segments: int) -> float:
    if total_segments <= 0:
        return 1.0

    completed = min(max(completed_segments, 0), total_segments)
    return PREPARING_PROGRESS_SHARE + SEGMENT_PROGRESS_SHARE * (completed / total_segments)
