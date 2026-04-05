import { ref, computed, shallowRef } from "vue";
import { useTimeline } from "./useTimeline";
import { useRuntimeState } from "./useRuntimeState";

type BlockCacheEntry = {
  buffer: AudioBuffer | null;
  promise: Promise<AudioBuffer>;
};

// module-level singletons (preserves state across route changes if needed)
const isPlaying = ref(false);
const currentSample = ref(0);
const currentSegmentId = ref<string | null>(null);

const audioCtx = shallowRef<AudioContext | null>(null);
const blockCache = new Map<string, BlockCacheEntry>();

// Scheduling state
let activeNodes: Array<{ node: AudioBufferSourceNode; blockIndex: number }> =
  [];
let startTimeSeconds = 0; // AudioContext.currentTime when playback started/seeked
let startOffsetSamples = 0; // The exact timeline sample value corresponding to startTimeSeconds
let animationFrameId: number | null = null;
let prefetchTimeoutId: number | null = null;

export function usePlayback() {
  const {
    timelineManifest,
    blockEntries,
    sampleRate,
    totalSamples,
    sampleToSegmentId,
    segmentIdToSampleRange,
  } = useTimeline();
  const { canMutate, lockedSegmentIds } = useRuntimeState();

  function getAudioCtx() {
    if (!audioCtx.value) {
      audioCtx.value = new AudioContext({
        sampleRate: sampleRate.value || 24000,
      });
    }
    if (audioCtx.value.state === "suspended") {
      void audioCtx.value.resume();
    }
    return audioCtx.value;
  }

  function fetchBlock(audioUrl: string): Promise<AudioBuffer> {
    if (blockCache.has(audioUrl)) {
      return blockCache.get(audioUrl)!.promise;
    }

    const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
    const fullUrl = API_BASE
      ? `${API_BASE.replace(/\/$/, "")}${audioUrl}`
      : audioUrl;

    const promise = fetch(fullUrl)
      .then((res) => {
        if (!res.ok) throw new Error("Fetch block audio failed");
        return res.arrayBuffer();
      })
      .then((ab) => getAudioCtx().decodeAudioData(ab))
      .then((buffer) => {
        const entry = blockCache.get(audioUrl);
        if (entry) entry.buffer = buffer;
        return buffer;
      });

    blockCache.set(audioUrl, { promise, buffer: null });
    return promise;
  }

  function clearActiveNodes() {
    for (const { node } of activeNodes) {
      node.onended = null;
      try {
        node.stop();
      } catch (e) {
        /* ignore */
      }
      try {
        node.disconnect();
      } catch (e) {
        /* ignore */
      }
    }
    activeNodes = [];
  }

  function pause() {
    if (!isPlaying.value) return;
    isPlaying.value = false;

    if (animationFrameId !== null) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    if (prefetchTimeoutId !== null) {
      clearTimeout(prefetchTimeoutId);
      prefetchTimeoutId = null;
    }

    // Calculate accurate pause position before clearing
    const ctx = getAudioCtx();
    const elapsedSeconds = ctx.currentTime - startTimeSeconds;
    currentSample.value = Math.min(
      totalSamples.value,
      startOffsetSamples + Math.floor(elapsedSeconds * sampleRate.value),
    );

    clearActiveNodes();
  }

  function updatePlayState() {
    if (!isPlaying.value) return;
    const ctx = getAudioCtx();
    const elapsedSeconds = ctx.currentTime - startTimeSeconds;
    const newSample =
      startOffsetSamples + Math.floor(elapsedSeconds * sampleRate.value);

    if (newSample >= totalSamples.value) {
      currentSample.value = totalSamples.value;
      isPlaying.value = false;
      return;
    }

    currentSample.value = newSample;
    currentSegmentId.value = sampleToSegmentId(newSample);
    animationFrameId = requestAnimationFrame(updatePlayState);
  }

  // Determine which block covers the requested sample
  function findBlockIndexForSample(sample: number) {
    const blocks = blockEntries.value;
    for (let i = 0; i < blocks.length; i++) {
      if (sample >= blocks[i].start_sample && sample < blocks[i].end_sample) {
        return i;
      }
    }
    return -1;
  }

  async function scheduleBlock(
    blockIndex: number,
    scheduleStartCtxTime: number,
    offsetSamplesInBlock: number,
  ) {
    if (blockIndex < 0 || blockIndex >= blockEntries.value.length) return;
    const block = blockEntries.value[blockIndex];

    try {
      const buffer = await fetchBlock(block.audio_url);
      // Check if we are still playing and haven't seeked away
      if (!isPlaying.value) return;

      const ctx = getAudioCtx();

      // If the schedule time is in the past, or very close, shift everything to "now" to avoid drops
      let startCtxTime = scheduleStartCtxTime;
      // We need offset in seconds to start reading from buffer
      let initialBufferOffset = offsetSamplesInBlock / sampleRate.value;

      if (startCtxTime < ctx.currentTime) {
        // We're late scheduling this block.
        const delay = ctx.currentTime - startCtxTime;
        startCtxTime = ctx.currentTime;
        initialBufferOffset += delay;
      }

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start(startCtxTime, initialBufferOffset);

      activeNodes.push({ node: source, blockIndex });

      // Schedule prefetching the next block before this one ends
      // Calculate how long this block will play
      const durationSeconds =
        buffer.length / buffer.sampleRate - initialBufferOffset;
      const nextBlockIndex = blockIndex + 1;

      if (nextBlockIndex < blockEntries.value.length) {
        // Start fetching early
        prefetchTimeoutId = window.setTimeout(
          () => {
            if (isPlaying.value) {
              void fetchBlock(blockEntries.value[nextBlockIndex].audio_url);
            }
          },
          Math.max(0, (durationSeconds - 2) * 1000),
        );

        source.onended = () => {
          // Check if this node is still relevant
          const t = activeNodes.findIndex((n) => n.node === source);
          if (t >= 0) activeNodes.splice(t, 1);

          if (isPlaying.value) {
            const nextCtxTime = startCtxTime + durationSeconds;
            void scheduleBlock(nextBlockIndex, nextCtxTime, 0);
          }
        };
      } else {
        source.onended = () => {
          const t = activeNodes.findIndex((n) => n.node === source);
          if (t >= 0) activeNodes.splice(t, 1);
          if (activeNodes.length === 0) {
            isPlaying.value = false;
            currentSample.value = totalSamples.value;
          }
        };
      }
    } catch (e) {
      console.error("Failed to schedule block", e);
      pause();
    }
  }

  function play() {
    if (!canMutate.value || isPlaying.value) return;

    if (currentSample.value >= totalSamples.value) {
      currentSample.value = 0;
    }

    isPlaying.value = true;
    const ctx = getAudioCtx();
    startTimeSeconds = ctx.currentTime;
    startOffsetSamples = currentSample.value;

    const startBlkIndex = findBlockIndexForSample(startOffsetSamples);
    if (startBlkIndex !== -1) {
      const block = blockEntries.value[startBlkIndex];
      const offsetInBlock = startOffsetSamples - block.start_sample;
      void scheduleBlock(startBlkIndex, startTimeSeconds, offsetInBlock);

      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      animationFrameId = requestAnimationFrame(updatePlayState);
    } else {
      isPlaying.value = false;
    }
  }

  function seekToSample(sample: number) {
    const wasPlaying = isPlaying.value;
    if (wasPlaying) pause();

    currentSample.value = Math.max(0, Math.min(sample, totalSamples.value));
    currentSegmentId.value = sampleToSegmentId(currentSample.value);

    if (wasPlaying) play();
  }

  function seekToSegment(segmentId: string) {
    if (lockedSegmentIds.value.has(segmentId)) return; // cannot seek to locked segment
    const range = segmentIdToSampleRange(segmentId);
    if (range) {
      seekToSample(range.start);
    }
  }

  return {
    isPlaying: computed(() => isPlaying.value),
    currentSample,
    currentSegmentId,
    play,
    pause,
    seekToSample,
    seekToSegment,
  };
}
