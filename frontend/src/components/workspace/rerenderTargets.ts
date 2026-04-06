export interface RerenderTargetSegment {
  segment_id: string;
  order_key: number;
  render_status: string;
}

export function resolveRerenderTargets(input: {
  dirtyTextSegmentIds: Set<string>;
  segments: RerenderTargetSegment[];
}) {
  const orderedIds = [...input.segments]
    .sort((left, right) => left.order_key - right.order_key)
    .map((segment) => segment.segment_id);

  const pendingIds = new Set(
    input.segments
      .filter((segment) => segment.render_status !== "ready")
      .map((segment) => segment.segment_id),
  );

  const merged = new Set<string>();
  for (const segmentId of orderedIds) {
    if (input.dirtyTextSegmentIds.has(segmentId) || pendingIds.has(segmentId)) {
      merged.add(segmentId);
    }
  }

  for (const segmentId of input.dirtyTextSegmentIds) {
    merged.add(segmentId);
  }

  return {
    segmentIds: Array.from(merged),
    count: merged.size,
  };
}
