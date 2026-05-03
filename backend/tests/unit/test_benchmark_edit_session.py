import json
from pathlib import Path

from backend.scripts.benchmark_edit_session import compare_with_optional_baseline, write_metrics


def _build_metrics() -> dict:
    return {
        "initialize_seconds_p50": 1.0,
        "segment_update_seconds_p50": 0.8,
        "pause_only_edge_update_seconds_p50": 0.3,
        "boundary_strategy_update_seconds_p50": 0.6,
        "restore_baseline_seconds_p50": 0.7,
        "initialize_inference_call_count": 3,
        "segment_update_inference_call_count": 1,
        "pause_only_edge_update_inference_call_count": 0,
        "peak_rss_mb": 512.0,
        "peak_gpu_memory_mb": 256.0,
    }


def test_write_metrics_persists_json_payload(tmp_path: Path):
    output_path = tmp_path / "benchmarks" / "latest.json"

    write_metrics(_build_metrics(), output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == _build_metrics()


def test_compare_with_optional_baseline_returns_zero_without_baseline():
    assert compare_with_optional_baseline(_build_metrics(), None) == 0


def test_compare_with_optional_baseline_returns_zero_when_not_regressed(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                **_build_metrics(),
                "initialize_seconds_p50": 1.2,
                "segment_update_seconds_p50": 0.9,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = compare_with_optional_baseline(_build_metrics(), baseline_path)

    assert result == 0


def test_compare_with_optional_baseline_returns_one_when_regressed(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                **_build_metrics(),
                "initialize_seconds_p50": 0.9,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = compare_with_optional_baseline(_build_metrics(), baseline_path)

    assert result == 1


def test_phase0_review_metrics_include_timing_and_inference_call_baseline_fields():
    metrics = _build_metrics()

    assert set(
        [
            "initialize_seconds_p50",
            "segment_update_seconds_p50",
            "pause_only_edge_update_seconds_p50",
            "initialize_inference_call_count",
            "segment_update_inference_call_count",
            "pause_only_edge_update_inference_call_count",
        ]
    ).issubset(metrics)
