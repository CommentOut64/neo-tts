import { describe, expect, it } from "vitest";

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

describe("segmentNavigation", () => {
it("播放位于第二段中部时，上一段跳到第一段段头", () => {
  expect(findPreviousSegmentStartSample(segments, 1500)).toBe(0);
});

it("播放位于第三段段头时，上一段跳到第二段段头", () => {
  expect(findPreviousSegmentStartSample(segments, 2000)).toBe(1000);
});

it("播放位于第二段中部时，下一段跳到第三段段头", () => {
  expect(findNextSegmentStartSample(segments, 1500, 3000)).toBe(2000);
});

it("播放位于最后一段中部时，下一段跳到时间线末尾", () => {
  expect(findNextSegmentStartSample(segments, 2500, 3000)).toBe(3000);
});
});
