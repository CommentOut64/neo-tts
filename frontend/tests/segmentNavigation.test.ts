import assert from "node:assert/strict";

import {
  findNextSegmentStartSample,
  findPreviousSegmentStartSample,
} from "../src/utils/segmentNavigation";
import type { TimelineSegmentEntry } from "../src/types/editSession";

const segments: TimelineSegmentEntry[] = [
  {
    segment_id: "seg-1",
    order_key: 0,
    start_sample: 0,
    end_sample: 1000,
    render_status: "ready",
    group_id: null,
    render_profile_id: null,
    voice_binding_id: null,
  },
  {
    segment_id: "seg-2",
    order_key: 1,
    start_sample: 1000,
    end_sample: 2000,
    render_status: "ready",
    group_id: null,
    render_profile_id: null,
    voice_binding_id: null,
  },
  {
    segment_id: "seg-3",
    order_key: 2,
    start_sample: 2000,
    end_sample: 3000,
    render_status: "ready",
    group_id: null,
    render_profile_id: null,
    voice_binding_id: null,
  },
];

assert.equal(
  findPreviousSegmentStartSample(segments, 1500),
  0,
  "播放位于第二段中部时，上一段应跳到第一段段头，而不是当前段段头",
);

assert.equal(
  findPreviousSegmentStartSample(segments, 2000),
  1000,
  "播放位于第三段段头时，上一段应跳到第二段段头",
);

assert.equal(
  findNextSegmentStartSample(segments, 1500, 3000),
  2000,
  "播放位于第二段中部时，下一段应跳到第三段段头",
);

assert.equal(
  findNextSegmentStartSample(segments, 2500, 3000),
  3000,
  "播放位于最后一段中部时，下一段应跳到时间线末尾",
);
