import { describe, expect, it } from "vitest";

import {
  resolvePlaybackCursor,
  useTimeline,
} from "../src/composables/useTimeline";
import type { TimelineManifest } from "../src/types/editSession";

function buildTimeline(): TimelineManifest {
  return {
    timeline_manifest_id: "timeline-1",
    document_id: "doc-1",
    document_version: 1,
    timeline_version: 1,
    sample_rate: 24000,
    playable_sample_span: [0, 9],
    block_entries: [
      {
        block_asset_id: "block-1",
        segment_ids: ["seg-1", "seg-2"],
        start_sample: 0,
        end_sample: 9,
        audio_sample_count: 9,
        audio_url: "/audio/block-1.wav",
      },
    ],
    segment_entries: [
      {
        segment_id: "seg-1",
        order_key: 1,
        start_sample: 0,
        end_sample: 3,
        render_status: "ready",
        group_id: null,
        render_profile_id: null,
        voice_binding_id: null,
      },
      {
        segment_id: "seg-2",
        order_key: 2,
        start_sample: 6,
        end_sample: 9,
        render_status: "ready",
        group_id: null,
        render_profile_id: null,
        voice_binding_id: null,
      },
    ],
    edge_entries: [
      {
        edge_id: "edge-1",
        left_segment_id: "seg-1",
        right_segment_id: "seg-2",
        pause_duration_seconds: 0.5,
        boundary_strategy: "crossfade_only",
        effective_boundary_strategy: "crossfade_only",
        boundary_start_sample: 3,
        boundary_end_sample: 4,
        pause_start_sample: 4,
        pause_end_sample: 6,
      },
    ],
    markers: [],
  };
}

describe("useTimeline playback cursor", () => {
  it("会按半开区间解析 before_start、segment、boundary、pause、ended", () => {
    const timeline = buildTimeline();

    expect(resolvePlaybackCursor(timeline, -1)).toEqual({
      sample: -1,
      kind: "before_start",
      segmentId: null,
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 0,
      spanEndSample: 0,
      progressInSpan: 0,
    });

    expect(resolvePlaybackCursor(timeline, 2)).toEqual({
      sample: 2,
      kind: "segment",
      segmentId: "seg-1",
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 0,
      spanEndSample: 3,
      progressInSpan: 2 / 3,
    });

    expect(resolvePlaybackCursor(timeline, 3)).toEqual({
      sample: 3,
      kind: "boundary",
      segmentId: null,
      edgeId: "edge-1",
      leftSegmentId: "seg-1",
      rightSegmentId: "seg-2",
      spanStartSample: 3,
      spanEndSample: 4,
      progressInSpan: 0,
    });

    expect(resolvePlaybackCursor(timeline, 4)).toEqual({
      sample: 4,
      kind: "pause",
      segmentId: null,
      edgeId: "edge-1",
      leftSegmentId: "seg-1",
      rightSegmentId: "seg-2",
      spanStartSample: 4,
      spanEndSample: 6,
      progressInSpan: 0,
    });

    expect(resolvePlaybackCursor(timeline, 5)).toEqual({
      sample: 5,
      kind: "pause",
      segmentId: null,
      edgeId: "edge-1",
      leftSegmentId: "seg-1",
      rightSegmentId: "seg-2",
      spanStartSample: 4,
      spanEndSample: 6,
      progressInSpan: 0.5,
    });

    expect(resolvePlaybackCursor(timeline, 6)).toEqual({
      sample: 6,
      kind: "segment",
      segmentId: "seg-2",
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 6,
      spanEndSample: 9,
      progressInSpan: 0,
    });

    expect(resolvePlaybackCursor(timeline, 9)).toEqual({
      sample: 9,
      kind: "ended",
      segmentId: null,
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 9,
      spanEndSample: 9,
      progressInSpan: 1,
    });
  });

  it("sampleToSegmentId 只在 sample 位于 segment 区间时返回段 id", () => {
    const timelineApi = useTimeline();
    timelineApi.setTimeline(buildTimeline());

    expect(timelineApi.sampleToSegmentId(2)).toBe("seg-1");
    expect(timelineApi.sampleToSegmentId(3)).toBeNull();
    expect(timelineApi.sampleToSegmentId(4)).toBeNull();
    expect(timelineApi.sampleToSegmentId(5)).toBeNull();
    expect(timelineApi.sampleToSegmentId(6)).toBe("seg-2");
    expect(timelineApi.sampleToSegmentId(9)).toBeNull();
  });

  it("segment 与 edge 区间重叠时会抛显式错误", () => {
    const timeline = buildTimeline();
    timeline.edge_entries = [
      {
        ...timeline.edge_entries[0],
        boundary_start_sample: 2,
        boundary_end_sample: 4,
      },
    ];

    expect(() => resolvePlaybackCursor(timeline, 2)).toThrow(
      /overlapping segment\/edge span/,
    );
  });

  it("sample 落在 playable span 内却未命中任何区间时会抛显式错误", () => {
    const timeline = buildTimeline();
    timeline.edge_entries = [];

    expect(() => resolvePlaybackCursor(timeline, 4)).toThrow(
      /matched no segment\/edge/,
    );
  });
});
