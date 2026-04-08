import assert from "node:assert/strict";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePlayback } from "../src/composables/usePlayback";
import { useTimeline } from "../src/composables/useTimeline";
import type { TimelineManifest } from "../src/types/editSession";

type GainEvent =
  | { type: "set"; value: number; time: number }
  | { type: "linearRamp"; value: number; time: number }
  | { type: "cancel"; time: number };

class FakeAudioParam {
  public value = 1;
  public readonly events: GainEvent[] = [];

  cancelScheduledValues(time: number) {
    this.events.push({ type: "cancel", time });
  }

  setValueAtTime(value: number, time: number) {
    this.value = value;
    this.events.push({ type: "set", value, time });
  }

  linearRampToValueAtTime(value: number, time: number) {
    this.value = value;
    this.events.push({ type: "linearRamp", value, time });
  }
}

class FakeGainNode {
  public readonly gain = new FakeAudioParam();
  public readonly connections: unknown[] = [];

  connect(_target: unknown) {
    this.connections.push(_target);
    return _target;
  }

  disconnect() {}
}

class FakeAudioBufferSourceNode {
  public buffer: FakeAudioBuffer | null = null;
  public onended: (() => void) | null = null;
  public readonly startCalls: Array<{ when: number; offset: number }> = [];
  public readonly stopCalls: Array<{ when: number | undefined }> = [];
  public readonly connections: unknown[] = [];

  connect(_target: unknown) {
    this.connections.push(_target);
    return _target;
  }

  disconnect() {}

  start(when = 0, offset = 0) {
    this.startCalls.push({ when, offset });
  }

  stop(when?: number) {
    this.stopCalls.push({ when });
  }
}

type FakeAudioBuffer = {
  sampleRate: number;
  length: number;
  duration: number;
  numberOfChannels: number;
};

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];

  public currentTime = 0;
  public state: AudioContextState = "running";
  public readonly destination = { kind: "destination" };
  public readonly gainNodes: FakeGainNode[] = [];
  public readonly sourceNodes: FakeAudioBufferSourceNode[] = [];

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  resume() {
    this.state = "running";
    return Promise.resolve();
  }

  createGain() {
    const node = new FakeGainNode();
    this.gainNodes.push(node);
    return node as unknown as GainNode;
  }

  createBufferSource() {
    const node = new FakeAudioBufferSourceNode();
    this.sourceNodes.push(node);
    return node as unknown as AudioBufferSourceNode;
  }

  decodeAudioData(_data: ArrayBuffer) {
    return Promise.resolve({
      sampleRate: 24000,
      length: 24000,
      duration: 1,
      numberOfChannels: 1,
    } as AudioBuffer);
  }
}

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function waitFor(
  predicate: () => boolean,
  message: string,
  maxAttempts = 20,
) {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (predicate()) return;
    await flushMicrotasks();
  }

  assert.fail(message);
}

function buildTimeline(): TimelineManifest {
  return {
    timeline_manifest_id: "timeline-1",
    document_id: "doc-1",
    document_version: 1,
    timeline_version: 1,
    sample_rate: 24000,
    playable_sample_span: [0, 24000],
    block_entries: [
      {
        block_asset_id: "block-1",
        segment_ids: ["seg-1"],
        start_sample: 0,
        end_sample: 24000,
        audio_sample_count: 24000,
        audio_url: "/audio/block-1.wav",
      },
    ],
    segment_entries: [
      {
        segment_id: "seg-1",
        order_key: 0,
        start_sample: 0,
        end_sample: 24000,
        render_status: "ready",
        group_id: null,
        render_profile_id: null,
        voice_binding_id: null,
      },
    ],
    edge_entries: [],
    markers: [],
  };
}

describe("usePlayback seek fade", () => {
afterEach(() => {
  delete (globalThis as typeof globalThis & { AudioContext?: unknown }).AudioContext;
  delete (globalThis as typeof globalThis & { fetch?: unknown }).fetch;
  delete (globalThis as typeof globalThis & { requestAnimationFrame?: unknown }).requestAnimationFrame;
  delete (globalThis as typeof globalThis & { cancelAnimationFrame?: unknown }).cancelAnimationFrame;
});

it("seekToSample 会先淡出旧 source，再淡入新 source", async () => {
  FakeAudioContext.instances.length = 0;

  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    writable: true,
    value: FakeAudioContext,
  });
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => "audio/wav" },
      arrayBuffer: async () => new ArrayBuffer(16),
    }),
  });
  Object.defineProperty(globalThis, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: () => 1,
  });
  Object.defineProperty(globalThis, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: () => {},
  });

  const { setTimeline } = useTimeline();
  setTimeline(buildTimeline());

  const playback = usePlayback();
  playback.play();
  await waitFor(
    () => {
      const ctx = FakeAudioContext.instances[0];
      return Boolean(ctx && ctx.sourceNodes.length > 0);
    },
    "初次播放应先启动旧 source，测试才能覆盖 seek 淡出",
  );

  const ctx = FakeAudioContext.instances[0];
  expect(ctx).toBeTruthy();

  ctx.currentTime = 0.25;
  playback.seekToSample(12000);
  await flushMicrotasks();

  expect(ctx.gainNodes.length).toBe(1);

  const gainEvents = ctx.gainNodes[0].gain.events;
  const fadeOutEvent = gainEvents.find(
    (event) =>
      event.type === "linearRamp" &&
      event.value === 0 &&
      event.time > 0.25,
  );
  const fadeInStartEvent = gainEvents.find(
    (event) =>
      event.type === "set" &&
      event.value === 0 &&
      event.time >= fadeOutEvent!.time,
  );
  const fadeInEvent = gainEvents.find(
    (event) =>
      event.type === "linearRamp" &&
      event.value === 1 &&
      event.time > fadeOutEvent!.time,
  );

  expect(fadeOutEvent).toBeTruthy();
  expect(fadeInStartEvent).toBeTruthy();
  expect(fadeInEvent).toBeTruthy();

  const oldSource = ctx.sourceNodes[0];
  expect(
    oldSource.stopCalls.some(
      (call) =>
        typeof call.when === "number" && call.when >= fadeOutEvent!.time,
    ),
  ).toBe(true);
});

it("warmAudioUrls 会提前拉取并解码 block 音频", async () => {
  FakeAudioContext.instances.length = 0;

  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: { get: () => "audio/wav" },
    arrayBuffer: async () => new ArrayBuffer(16),
  }));

  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    writable: true,
    value: FakeAudioContext,
  });
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: fetchMock,
  });

  const playback = usePlayback();
  await playback.warmAudioUrls(["/audio/block-99.wav", "/audio/block-100.wav"]);

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock).toHaveBeenNthCalledWith(1, "/audio/block-99.wav");
  expect(fetchMock).toHaveBeenNthCalledWith(2, "/audio/block-100.wav");
});
});
