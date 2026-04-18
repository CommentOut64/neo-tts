from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.schemas.edit_session import DocumentSnapshot, ExportSubtitleRequest, TimelineManifest
from backend.app.text.segment_standardizer import build_segment_display_text


@dataclass(frozen=True)
class _SubtitleCue:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


class SubtitleExportResult(BaseModel):
    format: str = Field(description="字幕格式。")
    file_extension: str = Field(description="导出文件扩展名。")
    payload: str = Field(description="最终字幕文件内容。")
    offset_seconds: float = Field(description="作用于全部字幕段的全局时间偏移。")
    strip_trailing_punctuation: bool = Field(
        default=False,
        description="是否去除了每段段末标点与尾随闭合符。",
    )


class SubtitleExportService:
    def export(
        self,
        *,
        request: ExportSubtitleRequest,
        snapshot: DocumentSnapshot,
        timeline: TimelineManifest,
    ) -> SubtitleExportResult:
        if request.format != "srt":
            raise ValueError(f"Unsupported subtitle format: {request.format}")
        payload = self._render_srt(
            request=request,
            snapshot=snapshot,
            timeline=timeline,
        )
        return SubtitleExportResult(
            format="srt",
            file_extension=".srt",
            payload=payload,
            offset_seconds=request.offset_seconds,
            strip_trailing_punctuation=request.strip_trailing_punctuation,
        )

    def _render_srt(
        self,
        *,
        request: ExportSubtitleRequest,
        snapshot: DocumentSnapshot,
        timeline: TimelineManifest,
    ) -> str:
        segment_map = {segment.segment_id: segment for segment in snapshot.segments}
        cues: list[_SubtitleCue] = []
        for index, entry in enumerate(timeline.segment_entries, start=1):
            segment = segment_map.get(entry.segment_id)
            if segment is None:
                raise EditSessionNotFoundError(f"Segment '{entry.segment_id}' not found in snapshot for subtitle export.")
            start_seconds = entry.start_sample / timeline.sample_rate
            end_seconds = entry.end_sample / timeline.sample_rate
            shifted_start, shifted_end = self._shift_segment_window(
                start_seconds,
                end_seconds,
                request.offset_seconds,
            )
            cues.append(
                _SubtitleCue(
                    index=index,
                    start_seconds=shifted_start,
                    end_seconds=shifted_end,
                    text=self._resolve_subtitle_text(
                        stem=segment.stem,
                        text_language=segment.text_language,
                        terminal_raw=segment.terminal_raw,
                        terminal_closer_suffix=segment.terminal_closer_suffix,
                        terminal_source=segment.terminal_source,
                        strip_trailing_punctuation=request.strip_trailing_punctuation,
                    ),
                )
            )
        return (
            "\n\n".join(
                [
                    "\n".join(
                        [
                            str(cue.index),
                            f"{self._format_srt_timestamp(cue.start_seconds)} --> {self._format_srt_timestamp(cue.end_seconds)}",
                            cue.text,
                        ]
                    )
                    for cue in cues
                ]
            )
            + "\n"
        )

    @staticmethod
    def _resolve_subtitle_text(
        *,
        stem: str,
        text_language: str,
        terminal_raw: str,
        terminal_closer_suffix: str,
        terminal_source: str,
        strip_trailing_punctuation: bool,
    ) -> str:
        if strip_trailing_punctuation:
            return stem
        return build_segment_display_text(
            stem=stem,
            text_language=text_language,
            terminal_raw=terminal_raw,
            terminal_closer_suffix=terminal_closer_suffix,
            terminal_source=terminal_source,
        )

    @staticmethod
    def _shift_segment_window(start_seconds: float, end_seconds: float, offset_seconds: float) -> tuple[float, float]:
        duration = max(end_seconds - start_seconds, 0.0)
        shifted_start = start_seconds + offset_seconds
        if shifted_start < 0:
            return 0.0, duration
        return shifted_start, shifted_start + duration

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        total_milliseconds = max(int(round(seconds * 1000)), 0)
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"
