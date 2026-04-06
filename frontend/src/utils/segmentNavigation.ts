import type { TimelineSegmentEntry } from "@/types/editSession";

function findSegmentIndexAtSample(
  segmentEntries: TimelineSegmentEntry[],
  sample: number,
) {
  for (let i = 0; i < segmentEntries.length; i++) {
    const segment = segmentEntries[i];
    if (sample < segment.start_sample) {
      return { kind: "before" as const, index: i };
    }
    if (sample < segment.end_sample) {
      return { kind: "inside" as const, index: i };
    }
  }

  return { kind: "after" as const, index: segmentEntries.length };
}

export function findPreviousSegmentStartSample(
  segmentEntries: TimelineSegmentEntry[],
  currentSample: number,
) {
  if (segmentEntries.length === 0) return 0;

  const location = findSegmentIndexAtSample(segmentEntries, currentSample);
  if (location.kind === "before") {
    return segmentEntries[0].start_sample;
  }
  if (location.kind === "inside") {
    return segmentEntries[Math.max(0, location.index - 1)].start_sample;
  }

  return segmentEntries[Math.max(0, segmentEntries.length - 2)]?.start_sample
    ?? segmentEntries[0].start_sample;
}

export function findNextSegmentStartSample(
  segmentEntries: TimelineSegmentEntry[],
  currentSample: number,
  totalSamples: number,
) {
  if (segmentEntries.length === 0) return totalSamples;

  const location = findSegmentIndexAtSample(segmentEntries, currentSample);
  if (location.kind === "before") {
    return segmentEntries[location.index].start_sample;
  }
  if (location.kind === "inside") {
    const nextIndex = location.index + 1;
    return nextIndex < segmentEntries.length
      ? segmentEntries[nextIndex].start_sample
      : totalSamples;
  }

  return totalSamples;
}
