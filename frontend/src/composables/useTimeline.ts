import { ref, computed } from "vue";
import type {
  PlaybackCursor,
  TimelineEdgeEntry,
  TimelineManifest,
  TimelineSegmentEntry,
} from "@/types/editSession";

const timelineManifest = ref<TimelineManifest | null>(null);

function buildCursor(
  sample: number,
  kind: PlaybackCursor["kind"],
  spanStartSample: number,
  spanEndSample: number,
  ids?: {
    segmentId?: string | null;
    edgeId?: string | null;
    leftSegmentId?: string | null;
    rightSegmentId?: string | null;
  },
): PlaybackCursor {
  const spanLength = spanEndSample - spanStartSample;
  const progressInSpan =
    kind === "ended"
      ? 1
      : spanLength > 0
        ? (sample - spanStartSample) / spanLength
        : 0;

  return {
    sample,
    kind,
    segmentId: ids?.segmentId ?? null,
    edgeId: ids?.edgeId ?? null,
    leftSegmentId: ids?.leftSegmentId ?? null,
    rightSegmentId: ids?.rightSegmentId ?? null,
    spanStartSample,
    spanEndSample,
    progressInSpan,
  };
}

function assertHalfOpenSpan(
  name: string,
  start: number,
  end: number,
): asserts start is number {
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    throw new Error(`[timeline] invalid ${name}: start/end must be finite`);
  }
  if (start > end) {
    throw new Error(`[timeline] invalid ${name}: start > end`);
  }
}

function validateTimelineManifest(manifest: TimelineManifest) {
  const [playableStart, playableEnd] = manifest.playable_sample_span;
  assertHalfOpenSpan("playable_sample_span", playableStart, playableEnd);

  const segmentIds = new Set<string>();
  let previousSegmentEnd = playableStart;
  for (const segment of manifest.segment_entries) {
    assertHalfOpenSpan(
      `segment ${segment.segment_id}`,
      segment.start_sample,
      segment.end_sample,
    );
    if (segment.start_sample < previousSegmentEnd) {
      throw new Error(
        `[timeline] overlapping segment span: ${segment.segment_id}`,
      );
    }
    previousSegmentEnd = segment.end_sample;
    segmentIds.add(segment.segment_id);
  }

  let previousEdgeEnd = playableStart;
  for (const edge of manifest.edge_entries) {
    if (!segmentIds.has(edge.left_segment_id) || !segmentIds.has(edge.right_segment_id)) {
      throw new Error(
        `[timeline] edge references missing segment: ${edge.edge_id}`,
      );
    }

    assertHalfOpenSpan(
      `edge boundary ${edge.edge_id}`,
      edge.boundary_start_sample,
      edge.boundary_end_sample,
    );
    assertHalfOpenSpan(
      `edge pause ${edge.edge_id}`,
      edge.pause_start_sample,
      edge.pause_end_sample,
    );

    if (edge.boundary_end_sample > edge.pause_start_sample) {
      throw new Error(
        `[timeline] overlapping boundary/pause span: ${edge.edge_id}`,
      );
    }
    if (edge.boundary_start_sample < previousEdgeEnd) {
      throw new Error(`[timeline] overlapping edge span: ${edge.edge_id}`);
    }
    previousEdgeEnd = edge.pause_end_sample;
  }

  for (const segment of manifest.segment_entries) {
    for (const edge of manifest.edge_entries) {
      const overlapsBoundary =
        segment.start_sample < edge.boundary_end_sample &&
        edge.boundary_start_sample < segment.end_sample;
      const overlapsPause =
        segment.start_sample < edge.pause_end_sample &&
        edge.pause_start_sample < segment.end_sample;
      if (overlapsBoundary || overlapsPause) {
        throw new Error(
          `[timeline] overlapping segment/edge span: ${segment.segment_id}/${edge.edge_id}`,
        );
      }
    }
  }
}

function resolveSegmentCursor(
  sample: number,
  segments: TimelineSegmentEntry[],
): PlaybackCursor | null {
  let left = 0;
  let right = segments.length - 1;

  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    const segment = segments[mid];

    if (sample < segment.start_sample) {
      right = mid - 1;
      continue;
    }

    if (sample >= segment.end_sample) {
      left = mid + 1;
      continue;
    }

    return buildCursor(
      sample,
      "segment",
      segment.start_sample,
      segment.end_sample,
      { segmentId: segment.segment_id },
    );
  }

  return null;
}

function resolveEdgeCursor(
  sample: number,
  edges: TimelineEdgeEntry[],
): PlaybackCursor | null {
  for (const edge of edges) {
    if (
      sample >= edge.boundary_start_sample &&
      sample < edge.boundary_end_sample
    ) {
      return buildCursor(
        sample,
        "boundary",
        edge.boundary_start_sample,
        edge.boundary_end_sample,
        {
          edgeId: edge.edge_id,
          leftSegmentId: edge.left_segment_id,
          rightSegmentId: edge.right_segment_id,
        },
      );
    }

    if (sample >= edge.pause_start_sample && sample < edge.pause_end_sample) {
      return buildCursor(
        sample,
        "pause",
        edge.pause_start_sample,
        edge.pause_end_sample,
        {
          edgeId: edge.edge_id,
          leftSegmentId: edge.left_segment_id,
          rightSegmentId: edge.right_segment_id,
        },
      );
    }
  }

  return null;
}

export function resolvePlaybackCursor(
  manifest: TimelineManifest,
  sample: number,
): PlaybackCursor {
  validateTimelineManifest(manifest);

  const [playableStart, playableEnd] = manifest.playable_sample_span;
  if (sample < playableStart) {
    return buildCursor(sample, "before_start", playableStart, playableStart);
  }

  const segmentCursor = resolveSegmentCursor(sample, manifest.segment_entries);
  if (segmentCursor) {
    return segmentCursor;
  }

  const edgeCursor = resolveEdgeCursor(sample, manifest.edge_entries);
  if (edgeCursor) {
    return edgeCursor;
  }

  if (sample >= playableEnd) {
    return buildCursor(sample, "ended", playableEnd, playableEnd);
  }

  throw new Error(
    `[timeline] sample ${sample} is inside playable span but matched no segment/edge`,
  );
}

export function useTimeline() {
  function setTimeline(manifest: TimelineManifest | null) {
    timelineManifest.value = manifest;
  }

  const sampleRate = computed(
    () => timelineManifest.value?.sample_rate || 24000,
  );
  const totalSamples = computed(
    () => timelineManifest.value?.playable_sample_span?.[1] || 0,
  );
  const blockEntries = computed(
    () => timelineManifest.value?.block_entries || [],
  );
  const segmentEntries = computed(
    () => timelineManifest.value?.segment_entries || [],
  );
  const edgeEntries = computed(
    () => timelineManifest.value?.edge_entries || [],
  );
  const segmentRangeById = computed(() => {
    const map = new Map<string, { start: number; end: number }>();
    for (const segment of segmentEntries.value) {
      map.set(segment.segment_id, {
        start: segment.start_sample,
        end: segment.end_sample,
      });
    }
    return map;
  });

  function sampleToSegmentId(sample: number): string | null {
    if (!timelineManifest.value) return null;
    const cursor = resolvePlaybackCursor(timelineManifest.value, sample);
    return cursor.kind === "segment" ? cursor.segmentId : null;
  }

  function segmentIdToSampleRange(
    segmentId: string,
  ): { start: number; end: number } | null {
    return segmentRangeById.value.get(segmentId) || null;
  }

  return {
    timelineManifest,
    setTimeline,
    sampleRate,
    totalSamples,
    blockEntries,
    segmentEntries,
    edgeEntries,
    segmentRangeById,
    sampleToSegmentId,
    segmentIdToSampleRange,
  };
}
