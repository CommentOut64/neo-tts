import { ref, computed } from "vue";
import type { TimelineManifest } from "@/types/editSession";

const timelineManifest = ref<TimelineManifest | null>(null);

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
    const segments = segmentEntries.value;
    if (segments.length === 0) return null;

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

      return segment.segment_id;
    }

    if (right >= 0 && right < segments.length) {
      return segments[right].segment_id;
    }

    return null;
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
    segmentRangeById,
    sampleToSegmentId,
    segmentIdToSampleRange,
  };
}
