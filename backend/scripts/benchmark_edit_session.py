from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
from typing import TypedDict

import psutil
import torch
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.settings import AppSettings, get_settings
from backend.app.main import create_app
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.services.voice_service import VoiceService

REAL_MODEL_VOICE_ID = "neuro2"
REAL_MODEL_TEXT_LANGUAGE = "zh"
REAL_MODEL_SEGMENT_BOUNDARY_MODE = "zh_period"
REAL_MODEL_TTS_TEXT = (
    "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。"
    "他放下话筒，摸着胡须，琢磨起来。"
    "不，他太愚蠢了。"
    "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。"
    "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。"
)
REAL_MODEL_UPDATED_FIRST_SEGMENT = (
    "他急忙冲到马路对面，回到办公室，沉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。"
)


class BenchmarkMetrics(TypedDict):
    initialize_seconds_p50: float
    segment_update_seconds_p50: float
    pause_only_edge_update_seconds_p50: float
    boundary_strategy_update_seconds_p50: float
    restore_baseline_seconds_p50: float
    peak_rss_mb: float
    peak_gpu_memory_mb: float | None


@dataclass(frozen=True)
class RealModelBenchmarkEnv:
    voice_id: str
    reference_audio_path: Path
    reference_text: str
    tts_text: str
    updated_first_segment_text: str
    text_language: str
    segment_boundary_mode: str


@dataclass
class PeakMemoryTracker:
    process: psutil.Process
    peak_rss_bytes: int = 0
    peak_gpu_bytes: int | None = None

    def sample(self) -> None:
        rss_bytes = self.process.memory_info().rss
        if rss_bytes > self.peak_rss_bytes:
            self.peak_rss_bytes = rss_bytes
        if torch.cuda.is_available():
            gpu_bytes = torch.cuda.max_memory_allocated()
            if self.peak_gpu_bytes is None or gpu_bytes > self.peak_gpu_bytes:
                self.peak_gpu_bytes = gpu_bytes

    @property
    def peak_rss_mb(self) -> float:
        return round(self.peak_rss_bytes / (1024 * 1024), 3)

    @property
    def peak_gpu_memory_mb(self) -> float | None:
        if self.peak_gpu_bytes is None:
            return None
        return round(self.peak_gpu_bytes / (1024 * 1024), 3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 edit-session 真实模型 benchmark")
    parser.add_argument("--output", required=True, help="metrics JSON 输出路径")
    parser.add_argument("--baseline", help="可选 baseline JSON，用于性能回退比较")
    parser.add_argument("--repetitions", type=int, default=3, help="每个场景重复次数，默认 3")
    parser.add_argument("--timeout-seconds", type=float, default=300.0, help="单个作业等待超时")
    return parser


def require_real_model_env() -> RealModelBenchmarkEnv:
    if os.getenv("GPT_SOVITS_E2E") != "1":
        raise RuntimeError("请先设置 GPT_SOVITS_E2E=1，再运行真实模型 benchmark。")

    settings = get_settings()
    try:
        voice = VoiceService(VoiceRepository(settings=settings)).get_voice(REAL_MODEL_VOICE_ID)
    except LookupError as exc:
        raise RuntimeError(f"缺少预设 voice '{REAL_MODEL_VOICE_ID}': {exc}") from exc

    reference_audio_path = Path(voice.ref_audio)
    if not reference_audio_path.is_absolute():
        reference_audio_path = (settings.project_root / reference_audio_path).resolve()
    if not reference_audio_path.exists():
        raise RuntimeError(f"参考音频不存在: {reference_audio_path}")

    return RealModelBenchmarkEnv(
        voice_id=REAL_MODEL_VOICE_ID,
        reference_audio_path=reference_audio_path,
        reference_text=voice.ref_text,
        tts_text=REAL_MODEL_TTS_TEXT,
        updated_first_segment_text=REAL_MODEL_UPDATED_FIRST_SEGMENT,
        text_language=REAL_MODEL_TEXT_LANGUAGE,
        segment_boundary_mode=REAL_MODEL_SEGMENT_BOUNDARY_MODE,
    )


def build_benchmark_settings(storage_root: Path) -> AppSettings:
    base_settings = get_settings()
    return AppSettings(
        project_root=base_settings.project_root,
        voices_config_path=base_settings.voices_config_path,
        managed_voices_dir=base_settings.managed_voices_dir,
        synthesis_results_dir=storage_root / "synthesis_results",
        inference_params_cache_file=storage_root / "state" / "params_cache.json",
        edit_session_db_file=storage_root / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=storage_root / "storage" / "edit_session" / "assets",
        edit_session_staging_ttl_seconds=base_settings.edit_session_staging_ttl_seconds,
        cnhubert_base_path=base_settings.cnhubert_base_path,
        bert_path=base_settings.bert_path,
    )


def _wait_for_terminal_job(
    client: TestClient,
    job_id: str,
    tracker: PeakMemoryTracker,
    *,
    timeout_seconds: float,
) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict | None = None
    while time.time() < deadline:
        tracker.sample()
        response = client.get(f"/v1/edit-session/render-jobs/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"查询作业 {job_id} 失败: {response.status_code} {response.text}")
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "cancelled", "failed"}:
            if payload["status"] != "completed":
                raise RuntimeError(f"作业 {job_id} 未成功完成: {json.dumps(payload, ensure_ascii=False)}")
            tracker.sample()
            return payload
        time.sleep(0.25)
    raise RuntimeError(f"作业 {job_id} 未在 {timeout_seconds:.1f}s 内进入终态: {last_payload}")


def _wait_for_snapshot_version(
    client: TestClient,
    version: int,
    tracker: PeakMemoryTracker,
    *,
    timeout_seconds: float,
) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict | None = None
    while time.time() < deadline:
        tracker.sample()
        response = client.get("/v1/edit-session/snapshot")
        if response.status_code != 200:
            raise RuntimeError(f"查询 snapshot 失败: {response.status_code} {response.text}")
        payload = response.json()
        last_payload = payload
        if payload["session_status"] == "ready" and payload["document_version"] == version:
            tracker.sample()
            return payload
        time.sleep(0.25)
    raise RuntimeError(f"snapshot 未在 {timeout_seconds:.1f}s 内到达 document_version={version}: {last_payload}")


def _measure_request(
    client: TestClient,
    method: str,
    path: str,
    tracker: PeakMemoryTracker,
    *,
    expected_version: int,
    timeout_seconds: float,
    json_body: dict | None = None,
) -> tuple[float, dict]:
    started_at = time.perf_counter()
    response = client.request(method, path, json=json_body)
    if response.status_code != 202:
        raise RuntimeError(f"{method} {path} 失败: {response.status_code} {response.text}")
    job_id = response.json()["job"]["job_id"]
    _wait_for_terminal_job(client, job_id, tracker, timeout_seconds=timeout_seconds)
    snapshot = _wait_for_snapshot_version(client, expected_version, tracker, timeout_seconds=timeout_seconds)
    return time.perf_counter() - started_at, snapshot


def _measure_initialize(
    client: TestClient,
    tracker: PeakMemoryTracker,
    *,
    env: RealModelBenchmarkEnv,
    timeout_seconds: float,
) -> tuple[float, dict]:
    return _measure_request(
        client,
        "POST",
        "/v1/edit-session/initialize",
        tracker,
        expected_version=1,
        timeout_seconds=timeout_seconds,
        json_body={
            "raw_text": env.tts_text,
            "text_language": env.text_language,
            "voice_id": env.voice_id,
            "segment_boundary_mode": env.segment_boundary_mode,
        },
    )


def _percentile50(samples: list[float]) -> float:
    if not samples:
        raise ValueError("benchmark samples 不能为空。")
    return round(statistics.median(samples), 4)


def run_benchmark_suite(
    *,
    env: RealModelBenchmarkEnv,
    repetitions: int,
    timeout_seconds: float,
) -> BenchmarkMetrics:
    if repetitions <= 0:
        raise ValueError("repetitions 必须大于 0。")

    process = psutil.Process(os.getpid())
    tracker = PeakMemoryTracker(process=process)
    if torch.cuda.is_available():
        try:
            torch.cuda.reset_peak_memory_stats()
        except RuntimeError:
            pass

    storage_root = Path(tempfile.mkdtemp(prefix="edit-session-benchmark-"))
    try:
        settings = build_benchmark_settings(storage_root)

        initialize_samples: list[float] = []
        segment_update_samples: list[float] = []
        pause_only_edge_update_samples: list[float] = []
        boundary_strategy_update_samples: list[float] = []
        restore_baseline_samples: list[float] = []

        app = create_app(settings=settings)
        with TestClient(app) as client:
            for _ in range(repetitions):
                delete_response = client.delete("/v1/edit-session")
                if delete_response.status_code != 204:
                    raise RuntimeError(f"删除旧会话失败: {delete_response.status_code} {delete_response.text}")

                initialize_duration, initial_snapshot = _measure_initialize(
                    client,
                    tracker,
                    env=env,
                    timeout_seconds=timeout_seconds,
                )
                initialize_samples.append(initialize_duration)

                segment_id = initial_snapshot["segments"][0]["segment_id"]
                edge_id = initial_snapshot["edges"][0]["edge_id"]
                baseline_text = initial_snapshot["segments"][0]["raw_text"]
                baseline_pause = initial_snapshot["edges"][0]["pause_duration_seconds"]
                baseline_strategy = initial_snapshot["edges"][0]["boundary_strategy"]

                segment_duration, segment_snapshot = _measure_request(
                    client,
                    "PATCH",
                    f"/v1/edit-session/segments/{segment_id}",
                    tracker,
                    expected_version=2,
                    timeout_seconds=timeout_seconds,
                    json_body={
                        "raw_text": env.updated_first_segment_text,
                        "text_language": env.text_language,
                    },
                )
                if segment_snapshot["segments"][0]["raw_text"] != env.updated_first_segment_text:
                    raise RuntimeError("segment_update 场景未得到预期文本结果。")
                segment_update_samples.append(segment_duration)

                pause_only_duration, pause_snapshot = _measure_request(
                    client,
                    "PATCH",
                    f"/v1/edit-session/edges/{edge_id}",
                    tracker,
                    expected_version=3,
                    timeout_seconds=timeout_seconds,
                    json_body={"pause_duration_seconds": 0.8},
                )
                if pause_snapshot["edges"][0]["pause_duration_seconds"] != 0.8:
                    raise RuntimeError("pause_only_edge_update 场景未得到预期停顿时长。")
                pause_only_edge_update_samples.append(pause_only_duration)

                boundary_strategy_duration, strategy_snapshot = _measure_request(
                    client,
                    "PATCH",
                    f"/v1/edit-session/edges/{edge_id}",
                    tracker,
                    expected_version=4,
                    timeout_seconds=timeout_seconds,
                    json_body={"boundary_strategy": "crossfade_only"},
                )
                if strategy_snapshot["edges"][0]["boundary_strategy"] != "crossfade_only":
                    raise RuntimeError("boundary_strategy_update 场景未得到预期边界策略。")
                boundary_strategy_update_samples.append(boundary_strategy_duration)

                restore_duration, restore_snapshot = _measure_request(
                    client,
                    "POST",
                    "/v1/edit-session/restore-baseline",
                    tracker,
                    expected_version=5,
                    timeout_seconds=timeout_seconds,
                )
                if restore_snapshot["segments"][0]["raw_text"] != baseline_text:
                    raise RuntimeError("restore_baseline 场景未恢复初始文本。")
                if restore_snapshot["edges"][0]["pause_duration_seconds"] != baseline_pause:
                    raise RuntimeError("restore_baseline 场景未恢复初始停顿时长。")
                if restore_snapshot["edges"][0]["boundary_strategy"] != baseline_strategy:
                    raise RuntimeError("restore_baseline 场景未恢复初始边界策略。")
                restore_baseline_samples.append(restore_duration)

        tracker.sample()
        return BenchmarkMetrics(
            initialize_seconds_p50=_percentile50(initialize_samples),
            segment_update_seconds_p50=_percentile50(segment_update_samples),
            pause_only_edge_update_seconds_p50=_percentile50(pause_only_edge_update_samples),
            boundary_strategy_update_seconds_p50=_percentile50(boundary_strategy_update_samples),
            restore_baseline_seconds_p50=_percentile50(restore_baseline_samples),
            peak_rss_mb=tracker.peak_rss_mb,
            peak_gpu_memory_mb=tracker.peak_gpu_memory_mb,
        )
    finally:
        # Windows 下 sqlite 句柄释放可能滞后，避免 benchmark 因临时目录删除失败而误报失败。
        for _ in range(5):
            try:
                shutil.rmtree(storage_root)
                break
            except PermissionError:
                time.sleep(0.2)


def write_metrics(metrics: BenchmarkMetrics, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_with_optional_baseline(metrics: BenchmarkMetrics, baseline_path: Path | None) -> int:
    if baseline_path is None:
        return 0
    if not baseline_path.exists():
        raise FileNotFoundError(f"baseline 文件不存在: {baseline_path}")

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    regressions: list[str] = []
    for key, current_value in metrics.items():
        baseline_value = baseline.get(key)
        if current_value is None or baseline_value is None:
            continue
        if float(current_value) > float(baseline_value):
            regressions.append(f"{key}: current={current_value} baseline={baseline_value}")

    if regressions:
        for item in regressions:
            print(item, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    args = build_parser().parse_args()
    env = require_real_model_env()
    metrics = run_benchmark_suite(
        env=env,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout_seconds,
    )
    output_path = Path(args.output)
    baseline_path = Path(args.baseline) if args.baseline else None
    write_metrics(metrics, output_path)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return compare_with_optional_baseline(metrics, baseline_path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
